import { act, fireEvent, render, renderHook, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { RichText } from '@/components/chat/rich-text';
import { Composer } from '@/components/chat/composer';
import { isLikelySpeakerEcho, useSpeaker } from '@/hooks/use-voice';
import { useVoiceSession } from '@/hooks/use-voice-session';
import { api } from '@/lib/api';
import { retrievalLabel, speechText, splitSpeechChunks } from '@/lib/format';

vi.mock('@/lib/api', () => ({
  api: { tts: vi.fn(), ttsStream: vi.fn(), stt: vi.fn() },
  apiUrl: (path: string) => path,
  describeError: () => 'Không tạo được giọng đọc.',
}));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe('Natural Vietnamese TTS formatting & chunking', () => {
  it('expands academic acronyms naturally without spelling IELTS/TOEIC/GPA/VND letter-by-letter', () => {
    const out = speechText('Đạt IELTS 5.5, TOEIC 450, GPA 3.2 và nhận 500,000 VNĐ/tháng từ quỹ HBKKHT tại HPU [1].');
    expect(out).toContain('ai eo 5.5');
    expect(out).toContain('tô ích 450');
    expect(out).toContain('điểm trung bình tích lũy 3.2');
    expect(out).toContain('đồng mỗi tháng');
    expect(out).toContain('học bổng khuyến khích học tập');
    expect(out).toContain('Đại học Hải Phòng');
    expect(out).not.toContain('I. E. L. T. S.');
    expect(out).not.toContain('T. O. E. I. C.');
    expect(out).not.toContain('[1]');
  });

  it('splits long text on sentence boundaries for fast time-to-first-audio', () => {
    const text = 'Câu một giải thích điều kiện học bổng. Câu hai nêu rõ điểm rèn luyện tối thiểu. Câu ba hướng dẫn thủ tục nhận tiền học bổng.';
    const chunks = splitSpeechChunks(text, 75);
    expect(chunks.length).toBeGreaterThanOrEqual(2);
    expect(chunks.join(' ')).toBe(text);
  });

  it('labels hybrid semantic retrieval providers clearly', () => {
    expect(retrievalLabel('bm25+multilingual-e5')).toContain('BM25 + E5');
    expect(retrievalLabel('bm25+gemini-embed')).toContain('Gemini');
  });
});

describe('RichText safe clickable URLs', () => {
  it('turns http(s) URLs into external links and strips trailing sentence punctuation', () => {
    render(<RichText text="Tra cứu tại https://dhhp.edu.vn/quy-che. Hoặc **https://portal.dhhp.edu.vn/login**, cảm ơn." />);
    const links = screen.getAllByRole('link');
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute('href', 'https://dhhp.edu.vn/quy-che');
    expect(links[0]).toHaveAttribute('target', '_blank');
    expect(links[0]).toHaveAttribute('rel', 'noopener noreferrer');
    expect(links[1]).toHaveAttribute('href', 'https://portal.dhhp.edu.vn/login');
  });

  it('never turns non-http protocols into links', () => {
    render(<RichText text="Không bấm javascript:alert(1) nhé." />);
    expect(screen.queryByRole('link')).toBeNull();
  });
});

describe('Live voice session state machine & anti-echo', () => {
  it('filters speaker echo accurately', () => {
    expect(isLikelySpeakerEcho(
      'Thời gian bảo lưu tối đa là 4 học kỳ chính',
      'Thời gian bảo lưu tối đa là 4 học kỳ chính. Hết thời hạn này sinh viên phải quay lại học.',
    )).toBe(true);
    expect(isLikelySpeakerEcho(
      'Điều kiện xét học bổng loại giỏi là gì',
      'Thời gian bảo lưu tối đa là 4 học kỳ chính.',
    )).toBe(false);
  });

  it('auto-submits after brief confirm delay, supports editing, barge-in, and auto-relisten', async () => {
    vi.useFakeTimers();
    const onRequestListen = vi.fn();
    const onStopListen = vi.fn();
    const onAutoSubmit = vi.fn(async () => {});
    let speakComplete: (() => void) | undefined;
    const speaker = {
      phase: 'idle' as 'idle' | 'loading' | 'playing',
      lastSpokenRef: { current: { text: '', endedAt: 0 } },
      unlock: vi.fn(),
      speak: vi.fn(async (_k: string, _t: string, opts?: { onComplete?: () => void }) => {
        speakComplete = opts?.onComplete;
      }),
      stop: vi.fn(),
    };

    const { result } = renderHook(() => useVoiceSession({
      supported: true, canSend: true, sending: false, sessionId: 's1',
      speaker, onRequestListen, onStopListen, onAutoSubmit, confirmDelayMs: 1200, cooldownMs: 900,
    }));

    act(() => result.current.toggleLive());
    expect(result.current.liveEnabled).toBe(true);
    expect(speaker.unlock).toHaveBeenCalledOnce();
    act(() => vi.advanceTimersByTime(100));
    expect(onRequestListen).toHaveBeenCalledTimes(1);

    // Final speech triggers confirm countdown, then auto-submits.
    act(() => result.current.handleFinalTranscript('Điều kiện bảo lưu là gì?', false));
    expect(result.current.pendingText).toBe('Điều kiện bảo lưu là gì?');
    expect(onAutoSubmit).not.toHaveBeenCalled();
    act(() => vi.advanceTimersByTime(1200));
    expect(onAutoSubmit).toHaveBeenCalledWith('Điều kiện bảo lưu là gì?');

    // Speaking answer syncs turnKey and schedules next listen after completion.
    act(() => result.current.speakAnswer('turn-1', 'Bảo lưu tối đa 4 học kỳ.', { autoSpeak: false }));
    expect(speaker.speak).toHaveBeenCalledWith('turn-1', 'Bảo lưu tối đa 4 học kỳ.', expect.any(Object));
    act(() => speakComplete?.());
    act(() => vi.advanceTimersByTime(900));
    expect(onRequestListen).toHaveBeenCalledTimes(2);

    // Echo matching recent assistant speech is ignored instead of re-sending.
    speaker.lastSpokenRef.current = { text: 'Bảo lưu tối đa 4 học kỳ chính tại trường', endedAt: Date.now() };
    act(() => result.current.handleFinalTranscript('Bảo lưu tối đa 4 học kỳ chính', false));
    expect(result.current.livePaused).toBe(true);
    expect(onAutoSubmit).toHaveBeenCalledTimes(1);

    // Barge-in interrupts speech and immediately starts listening.
    act(() => result.current.bargeIn());
    expect(speaker.stop).toHaveBeenCalled();
    expect(onRequestListen).toHaveBeenCalledTimes(3);
  });
});

describe('useSpeaker browser speechSynthesis fallback', () => {
  it('falls back to window.speechSynthesis when server TTS fails', async () => {
    vi.mocked(api.ttsStream).mockRejectedValueOnce(new Error('edge down'));
    vi.mocked(api.tts).mockRejectedValueOnce(new Error('edge down'));

    const speakSpy = vi.fn((u: { onend?: () => void }) => {
      setTimeout(() => u.onend?.(), 0);
    });
    vi.stubGlobal('speechSynthesis', {
      getVoices: () => [{ lang: 'vi-VN', name: 'Vietnamese' }],
      cancel: vi.fn(),
      speak: speakSpy,
    });
    vi.stubGlobal('SpeechSynthesisUtterance', class {
      text: string; lang = ''; rate = 1; voice: unknown;
      onstart: (() => void) | null = null; onend: (() => void) | null = null; onerror: (() => void) | null = null;
      constructor(t: string) { this.text = t; }
    });

    const { result } = renderHook(() => useSpeaker('vi-VN-HoaiMyNeural', '+0%'));
    await act(async () => {
      await result.current.speak('turn-42', 'Xin chào sinh viên.');
    });
    expect(speakSpy).toHaveBeenCalledOnce();
    expect(result.current.error).toBeNull();
    expect(result.current.phase).toBe('idle');
  });
});

describe('Composer truthful AI state & Popover date', () => {
  it('disables AI toggle when llmAvailable is false and hides raw date input inside Popover', () => {
    const onToggleLive = vi.fn();
    render(
      <Composer
        value="" onChange={vi.fn()} onSubmit={vi.fn()} canSend blockedReason={null}
        refDate="" onRefDate={vi.fn()} useAi={false} onUseAi={vi.fn()}
        llmAvailable={false} onToggleLive={onToggleLive}
      />,
    );
    expect(screen.getByTestId('button-toggle-ai')).toBeDisabled();
    expect(screen.getByTestId('button-toggle-ai')).toHaveTextContent('AI chưa bật trên máy chủ');
    expect(screen.queryByTestId('input-ref-date')).toBeNull();
    fireEvent.click(screen.getByTestId('button-ref-date-toggle'));
    expect(screen.getByTestId('input-ref-date')).toBeInTheDocument();
  });
});
