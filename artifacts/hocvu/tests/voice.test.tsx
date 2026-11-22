import { useState } from 'react';
import { act, fireEvent, render, renderHook, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { speechChunks, useDictation, useSpeaker } from '@/hooks/use-voice';
import { api } from '@/lib/api';
import { Composer } from '@/components/chat/composer';

vi.mock('@/lib/api', () => ({
  api: { tts: vi.fn() },
  apiUrl: (path: string) => path,
  describeError: () => 'Không tạo được giọng đọc.',
}));

type ResultEvent = {
  resultIndex: number;
  results: { isFinal: boolean; 0: { transcript: string } }[];
};

class Recognition {
  static instances: Recognition[] = [];
  lang = '';
  interimResults = false;
  continuous = true;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  onerror: ((event: { error: string }) => void) | null = null;
  onresult: ((event: ResultEvent) => void) | null = null;
  start = vi.fn();
  stop = vi.fn();
  abort = vi.fn();
  constructor() { Recognition.instances.push(this); }
}

const latest = () => Recognition.instances[Recognition.instances.length - 1];
const event = (parts: [string, boolean][], resultIndex = 0): ResultEvent => ({
  resultIndex,
  results: parts.map(([transcript, isFinal]) => ({ isFinal, 0: { transcript } })),
});

beforeEach(() => {
  Recognition.instances = [];
  vi.stubGlobal('SpeechRecognition', Recognition);
  vi.stubGlobal('webkitSpeechRecognition', undefined);
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('Vietnamese dictation lifecycle', () => {
  it('shows startup immediately and uses Vietnamese recognition', () => {
    const { result } = renderHook(() => useDictation(vi.fn()));
    act(() => result.current.start());
    expect(result.current.phase).toBe('starting');
    expect(result.current.listening).toBe(true);
    expect(latest().lang).toBe('vi-VN');
    expect(latest().continuous).toBe(false);
    act(() => latest().onstart?.());
    expect(result.current.phase).toBe('listening');
  });

  it('keeps earlier final phrases when later interim results change', () => {
    const onText = vi.fn();
    const { result } = renderHook(() => useDictation(onText));
    act(() => result.current.start());
    act(() => latest().onresult?.(event([['Điều kiện', true], ['học bổng', false]], 1)));
    expect(onText).toHaveBeenLastCalledWith('Điều kiện học bổng', false);
    act(() => latest().onresult?.(event([['Điều kiện', true], ['học bổng là gì?', true]], 1)));
    expect(onText).toHaveBeenLastCalledWith('Điều kiện học bổng là gì?', true);
  });

  it('ignores queued transcript and end events after abort and restart', () => {
    const onText = vi.fn();
    const { result } = renderHook(() => useDictation(onText));
    act(() => result.current.start());
    const old = latest();
    const oldResult = old.onresult!;
    const oldEnd = old.onend!;
    act(() => result.current.abort());
    act(() => result.current.start());
    act(() => {
      oldResult(event([['Câu hỏi cũ', true]]));
      oldEnd();
    });
    expect(onText).not.toHaveBeenCalled();
    expect(result.current.phase).toBe('starting');
    expect(old.abort).toHaveBeenCalledOnce();
  });

  it('accepts final transcript while stopping, then closes cleanly', () => {
    const onText = vi.fn();
    const { result } = renderHook(() => useDictation(onText));
    act(() => result.current.start());
    const rec = latest();
    act(() => result.current.stop());
    expect(result.current.phase).toBe('stopping');
    act(() => {
      rec.onresult?.(event([['Bảo lưu học tập', true]]));
      rec.onend?.();
    });
    expect(onText).toHaveBeenCalledWith('Bảo lưu học tập', true);
    expect(result.current.phase).toBe('idle');
    expect(rec.onresult).toBeNull();
  });

  it('does not return to listening when a delayed start event follows stop', () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useDictation(vi.fn()));
    act(() => result.current.start());
    act(() => result.current.stop());
    act(() => latest().onstart?.());
    expect(result.current.phase).toBe('stopping');
    act(() => vi.advanceTimersByTime(5000));
    expect(result.current.phase).toBe('idle');
  });

  it('recovers from permission denial even if the browser omits onend', () => {
    const { result } = renderHook(() => useDictation(vi.fn()));
    act(() => result.current.start());
    act(() => latest().onerror?.({ error: 'not-allowed' }));
    expect(result.current.phase).toBe('idle');
    expect(result.current.error).toContain('quyền micro');
    act(() => result.current.start());
    expect(Recognition.instances).toHaveLength(2);
    expect(result.current.error).toBeNull();
  });

  it('times out a stalled microphone startup without capturing indefinitely', () => {
    vi.useFakeTimers();
    const { result } = renderHook(() => useDictation(vi.fn()));
    act(() => result.current.start());
    act(() => vi.advanceTimersByTime(20000));
    expect(result.current.phase).toBe('idle');
    expect(latest().abort).toHaveBeenCalledOnce();
    expect(result.current.error).toContain('quyền truy cập');
  });

  it('ignores late callbacks after unmount and cancels timers', () => {
    vi.useFakeTimers();
    const onText = vi.fn();
    const { result, unmount } = renderHook(() => useDictation(onText));
    act(() => result.current.start());
    const late = latest().onresult!;
    unmount();
    late(event([['Không được chuyển sang hội thoại mới', true]]));
    expect(onText).not.toHaveBeenCalled();
    expect(latest().abort).toHaveBeenCalledOnce();
    expect(vi.getTimerCount()).toBe(0);
  });

  it('reports unsupported browsers explicitly', () => {
    vi.stubGlobal('SpeechRecognition', undefined);
    const { result } = renderHook(() => useDictation(vi.fn()));
    expect(result.current.supported).toBe(false);
    act(() => result.current.start());
    expect(result.current.error).toContain('chưa hỗ trợ');
  });

  it('limits transcripts to the API question limit', () => {
    const onText = vi.fn();
    const { result } = renderHook(() => useDictation(onText));
    act(() => result.current.start());
    act(() => latest().onresult?.(event([['a'.repeat(5000), true]])));
    expect(onText.mock.calls[0][0]).toHaveLength(4000);
  });
});

describe('Speech playback ownership', () => {
  it('does not create audio when a cancelled TTS request resolves late', async () => {
    let finish!: (value: { status: string; audio_url: string }) => void;
    vi.mocked(api.tts).mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
    const audio = vi.fn();
    vi.stubGlobal('Audio', audio);
    const { result } = renderHook(() => useSpeaker('vi-VN-HoaiMyNeural', '+0%'));
    let pending!: Promise<void>;
    act(() => { pending = result.current.speak('old', 'Câu trả lời cũ'); });
    act(() => result.current.stop());
    await act(async () => { finish({ status: 'ok', audio_url: '/audio/old.mp3' }); await pending; });
    expect(audio).not.toHaveBeenCalled();
    expect(result.current.phase).toBe('idle');
  });

  it('cannot start audio from a late chat response after leaving the page', async () => {
    const { result, unmount } = renderHook(() => useSpeaker('vi-VN-HoaiMyNeural', '+0%'));
    const speak = result.current.speak;
    unmount();
    await speak('late', 'Không phát sau khi rời trang');
    expect(api.tts).not.toHaveBeenCalled();
  });
});

describe('Browser voice fallback', () => {
  class Utterance {
    lang = ''; voice: unknown = null; rate = 1;
    onend: (() => void) | null = null;
    onerror: ((event: { error: string }) => void) | null = null;
    constructor(public text: string) {}
  }
  const vietnamese = { lang: 'vi-VN', name: 'Tiếng Việt' };
  function installSynth(voices: unknown[] = [vietnamese]) {
    const spoken: Utterance[] = [];
    const synth = { speak: vi.fn((u: Utterance) => { spoken.push(u); }), cancel: vi.fn(), getVoices: () => voices };
    vi.stubGlobal('SpeechSynthesisUtterance', Utterance);
    Object.defineProperty(window, 'speechSynthesis', { value: synth, configurable: true });
    return { synth, spoken };
  }
  afterEach(() => { delete (window as unknown as Record<string, unknown>).speechSynthesis; });

  it('reads with the browser voice when the server voice is unavailable', async () => {
    const { synth, spoken } = installSynth();
    vi.mocked(api.tts).mockRejectedValueOnce(new Error('503'));
    const { result } = renderHook(() => useSpeaker('vi-VN-HoaiMyNeural', '+10%'));
    await act(async () => { await result.current.speak('turn', 'Câu thứ nhất. Câu thứ hai.'); });
    expect(result.current.phase).toBe('playing');
    expect(result.current.source).toBe('browser');
    expect(result.current.error).toBeNull();
    expect(spoken.map((u) => u.text)).toEqual(['Câu thứ nhất.']);
    expect(spoken[0].lang).toBe('vi-VN');
    expect(spoken[0].voice).toBe(vietnamese);
    expect(spoken[0].rate).toBeCloseTo(1.1);
    act(() => spoken[0].onend?.());
    expect(spoken.map((u) => u.text)).toEqual(['Câu thứ nhất.', 'Câu thứ hai.']);
    act(() => spoken[1].onend?.());
    expect(result.current.phase).toBe('idle');
    expect(result.current.activeKey).toBeNull();
    expect(synth.speak).toHaveBeenCalledTimes(2);
  });

  it('stops the browser voice and ignores its late callbacks', async () => {
    const { synth, spoken } = installSynth();
    vi.mocked(api.tts).mockRejectedValueOnce(new Error('503'));
    const { result } = renderHook(() => useSpeaker('vi-VN-HoaiMyNeural', '+0%'));
    await act(async () => { await result.current.speak('turn', 'Câu thứ nhất. Câu thứ hai.'); });
    act(() => result.current.stop());
    expect(synth.cancel).toHaveBeenCalled();
    expect(result.current.phase).toBe('idle');
    act(() => { spoken[0].onend?.(); spoken[0].onerror?.({ error: 'synthesis-failed' }); });
    expect(synth.speak).toHaveBeenCalledTimes(1);
    expect(result.current.error).toBeNull();
  });

  it('starts one fallback when the audio error and rejected play() both fire', async () => {
    const { synth } = installSynth();
    vi.mocked(api.tts).mockResolvedValueOnce({ status: 'ok', audio_url: '/api/audio/a.mp3' });
    let element!: { onerror: (() => void) | null };
    vi.stubGlobal('Audio', vi.fn(function Audio(this: Record<string, unknown>) {
      Object.assign(this, {
        onended: null, onerror: null, pause: vi.fn(), load: vi.fn(), removeAttribute: vi.fn(),
        play: () => { element.onerror?.(); return Promise.reject(new Error('decode')); },
      });
      element = this as unknown as typeof element;
    }));
    const { result } = renderHook(() => useSpeaker('vi-VN-HoaiMyNeural', '+0%'));
    await act(async () => { await result.current.speak('turn', 'Một câu trả lời.'); });
    await act(async () => { await Promise.resolve(); });
    expect(synth.speak).toHaveBeenCalledTimes(1);
    expect(result.current.source).toBe('browser');
    expect(result.current.phase).toBe('playing');
  });

  it('explains the failure when the browser has no Vietnamese voice', async () => {
    const { synth } = installSynth([{ lang: 'en-US', name: 'English' }]);
    vi.mocked(api.tts).mockRejectedValueOnce(new Error('503'));
    const { result } = renderHook(() => useSpeaker('vi-VN-HoaiMyNeural', '+0%'));
    await act(async () => { await result.current.speak('turn', 'Một câu trả lời.'); });
    expect(synth.speak).not.toHaveBeenCalled();
    expect(result.current.phase).toBe('idle');
    expect(result.current.error).toContain('không có giọng đọc tiếng Việt');
  });

  it('does not fall back after the listener cancels the request', async () => {
    const { synth } = installSynth();
    vi.mocked(api.tts).mockRejectedValueOnce(new DOMException('aborted', 'AbortError'));
    const { result } = renderHook(() => useSpeaker('vi-VN-HoaiMyNeural', '+0%'));
    await act(async () => { await result.current.speak('turn', 'Một câu trả lời.'); });
    expect(synth.speak).not.toHaveBeenCalled();
    expect(result.current.phase).toBe('idle');
    expect(result.current.error).toBeNull();
  });

  it('splits long answers into short spoken parts without losing text', () => {
    const long = `${'từ '.repeat(120).trim()}. Câu ngắn.`;
    const parts = speechChunks(long);
    expect(parts.every((part) => part.length <= 180)).toBe(true);
    expect(parts.join(' ')).toBe(long);
    expect(speechChunks('   ')).toEqual([]);
  });
});

describe('Voice composer integration', () => {
  function Harness({ canSend = true, voiceRequest = 0, onSubmit = vi.fn(), onVoiceStart = vi.fn() }) {
    const [value, setValue] = useState('Em muốn hỏi');
    return <Composer value={value} onChange={setValue} onSubmit={onSubmit} canSend={canSend}
      blockedReason={null} refDate="" onRefDate={vi.fn()} useAi={false} onUseAi={vi.fn()}
      onVoiceStart={onVoiceStart} voiceRequest={voiceRequest} />;
  }

  it('stops playback, appends speech to the draft and never submits automatically', () => {
    const onSubmit = vi.fn();
    const onVoiceStart = vi.fn();
    render(<Harness onSubmit={onSubmit} onVoiceStart={onVoiceStart} />);
    fireEvent.click(screen.getByTestId('button-mic'));
    expect(onVoiceStart).toHaveBeenCalledOnce();
    act(() => latest().onresult?.(event([['về học bổng', true]])));
    expect(screen.getByTestId('input-question')).toHaveValue('Em muốn hỏi về học bổng');
    expect(onSubmit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByTestId('button-send'));
    expect(onSubmit).toHaveBeenCalledOnce();
    expect(latest().abort).toHaveBeenCalledOnce();
  });

  it('preserves manual edits against late recognition results', () => {
    render(<Harness />);
    fireEvent.click(screen.getByTestId('button-mic'));
    const lateResult = latest().onresult!;
    fireEvent.change(screen.getByTestId('input-question'), { target: { value: 'Câu hỏi đã sửa' } });
    act(() => lateResult(event([['Kết quả cũ', true]])));
    expect(screen.getByTestId('input-question')).toHaveValue('Câu hỏi đã sửa');
    expect(latest().abort).toHaveBeenCalledOnce();
  });

  it('aborts capture and disables restart when the conversation becomes blocked', () => {
    const { rerender } = render(<Harness />);
    fireEvent.click(screen.getByTestId('button-mic'));
    rerender(<Harness canSend={false} />);
    expect(latest().abort).toHaveBeenCalledOnce();
    expect(screen.getByTestId('button-mic')).toBeDisabled();
  });

  it('starts from a welcome request but does not replay the request after remount', () => {
    const view = render(<Harness voiceRequest={0} />);
    view.rerender(<Harness voiceRequest={1} />);
    expect(Recognition.instances).toHaveLength(1);
    expect(screen.getByTestId('input-question')).not.toHaveFocus();
    view.unmount();
    render(<Harness voiceRequest={1} />);
    expect(Recognition.instances).toHaveLength(1);
  });

  it('shows the question limit on small screens too', () => {
    render(<Harness />);
    fireEvent.change(screen.getByTestId('input-question'), { target: { value: 'a'.repeat(3999) } });
    expect(screen.getByText('3999/4000')).toHaveAttribute('role', 'status');
    expect(screen.getByText('3999/4000')).not.toHaveClass('hidden');
  });
});
