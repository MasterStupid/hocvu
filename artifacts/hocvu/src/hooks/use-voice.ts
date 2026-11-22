import { useCallback, useEffect, useRef, useState } from 'react';
import { api, apiUrl, describeError } from '@/lib/api';
import { speechText } from '@/lib/format';

/* ---------- Text to speech: server MP3 first, browser voice as fallback ---------- */
export type SpeechSource = 'server' | 'browser';

const browserSynth = (): SpeechSynthesis | null =>
  typeof window !== 'undefined' && 'speechSynthesis' in window && typeof SpeechSynthesisUtterance !== 'undefined'
    ? window.speechSynthesis : null;

/** A voice, `undefined` when the list is still unknown, or `null` when no Vietnamese voice exists. */
async function vietnameseVoice(synth: SpeechSynthesis): Promise<SpeechSynthesisVoice | null | undefined> {
  let voices = synth.getVoices();
  if (!voices.length) {
    // Chrome fills the list asynchronously; do not wait indefinitely.
    voices = await new Promise<SpeechSynthesisVoice[]>((resolve) => {
      const done = () => { clearTimeout(timer); synth.removeEventListener?.('voiceschanged', done); resolve(synth.getVoices()); };
      const timer = setTimeout(done, 800);
      synth.addEventListener?.('voiceschanged', done);
    });
  }
  if (!voices.length) return undefined;
  return voices.find((v) => /^vi([-_]|$)/i.test(v.lang)) ?? null;
}

/** Long utterances are cut off by some browsers, so speak sentence-sized parts. */
export function speechChunks(text: string, max = 180): string[] {
  const parts: string[] = [];
  for (const sentence of text.split(/(?<=[.!?;:])\s+|\n+/).map((x) => x.trim()).filter(Boolean)) {
    let rest = sentence;
    while (rest.length > max) {
      const cut = rest.lastIndexOf(' ', max);
      const at = cut > max / 2 ? cut : max;
      parts.push(rest.slice(0, at).trim());
      rest = rest.slice(at).trim();
    }
    if (rest) parts.push(rest);
  }
  return parts;
}

const browserRate = (rate: string) => {
  const pct = Number.parseInt(rate, 10);
  return Number.isFinite(pct) ? Math.min(2, Math.max(0.5, 1 + pct / 100)) : 1;
};

export function useSpeaker(voice: string, rate: string) {
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [phase, setPhase] = useState<'idle' | 'loading' | 'playing'>('idle');
  const [source, setSource] = useState<SpeechSource>('server');
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const ctrlRef = useRef<AbortController | null>(null);
  const idRef = useRef(0);
  const mountedRef = useRef(true);

  const release = () => {
    const a = audioRef.current;
    audioRef.current = null;
    if (a) { a.onended = null; a.onerror = null; a.pause(); a.removeAttribute('src'); a.load(); }
  };

  // Every playback path shares this lifecycle: invalidate ownership first so
  // late audio/speech callbacks cannot restart or finish a newer request.
  const stop = useCallback(() => {
    idRef.current += 1;
    ctrlRef.current?.abort();
    ctrlRef.current = null;
    release();
    try { browserSynth()?.cancel(); } catch { /* nothing is speaking */ }
    setActiveKey(null);
    setPhase('idle');
  }, []);

  /** Resolves false when this browser cannot read Vietnamese aloud. */
  const speakWithBrowser = useCallback(async (id: number, text: string): Promise<boolean> => {
    const synth = browserSynth();
    if (!synth) return false;
    const chosen = await vietnameseVoice(synth);
    if (id !== idRef.current) return true;
    if (chosen === null) return false;
    const parts = speechChunks(text);
    if (!parts.length) return false;
    let index = 0;
    const finish = (message?: string) => {
      if (id !== idRef.current) return;
      idRef.current += 1;
      try { synth.cancel(); } catch { /* already silent */ }
      setActiveKey(null); setPhase('idle');
      if (message) setError(message);
    };
    const next = () => {
      if (id !== idRef.current) return;
      if (index >= parts.length) { finish(); return; }
      const utterance = new SpeechSynthesisUtterance(parts[index]);
      index += 1;
      utterance.lang = 'vi-VN';
      if (chosen) utterance.voice = chosen;
      utterance.rate = browserRate(rate);
      utterance.onend = next;
      utterance.onerror = (event) => {
        if (id !== idRef.current || event.error === 'canceled' || event.error === 'interrupted') return;
        finish('Trình duyệt không đọc được câu trả lời. Hãy thử lại sau ít phút.');
      };
      synth.speak(utterance);
    };
    try { synth.cancel(); } catch { /* already silent */ }
    setSource('browser'); setPhase('playing');
    next();
    return true;
  }, [rate]);

  const speak = useCallback(async (key: string, text: string) => {
    if (!mountedRef.current) return;
    stop();
    const id = idRef.current;
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;
    const spoken = speechText(text).slice(0, 4000);
    setActiveKey(key); setPhase('loading'); setSource('server'); setError(null);
    // The audio error event and a rejected play() promise can both report the
    // same failure; only the first may start the browser voice.
    let fellBack = false;
    const fallback = async (message: string) => {
      if (fellBack || id !== idRef.current) return;
      fellBack = true;
      release();
      const ok = await speakWithBrowser(id, spoken);
      if (ok || id !== idRef.current) return;
      setActiveKey(null); setPhase('idle');
      setError(`${message} Trình duyệt này cũng không có giọng đọc tiếng Việt để thay thế.`);
    };
    try {
      const { audio_url } = await api.tts(spoken, voice, rate, ctrl.signal);
      if (id !== idRef.current) return;
      const audio = new Audio(apiUrl(audio_url));
      audioRef.current = audio;
      audio.onended = () => { if (id === idRef.current) { release(); setActiveKey(null); setPhase('idle'); } };
      audio.onerror = () => { void fallback('Không phát được tệp âm thanh.'); };
      await audio.play();
      if (id === idRef.current && !fellBack) setPhase('playing');
    } catch (e) {
      if (id !== idRef.current) return;
      if (e instanceof DOMException && e.name === 'AbortError') { release(); setActiveKey(null); setPhase('idle'); return; }
      if (e instanceof DOMException && e.name === 'NotAllowedError') {
        release(); setActiveKey(null); setPhase('idle');
        setError('Trình duyệt chặn tự phát âm thanh. Hãy bấm Nghe để phát.');
        return;
      }
      await fallback(describeError(e, 'Không tạo được giọng đọc.'));
    }
  }, [rate, speakWithBrowser, stop, voice]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false; idRef.current += 1; ctrlRef.current?.abort(); release();
      try { browserSynth()?.cancel(); } catch { /* nothing is speaking */ }
    };
  }, []);

  return { activeKey, phase, source, error, clearError: () => setError(null), speak, stop };
}

/* ---------- Speech recognition (vi-VN) ---------- */
interface RecognitionResultLike { isFinal: boolean; 0: { transcript: string } }
interface RecognitionEventLike { resultIndex: number; results: ArrayLike<RecognitionResultLike> }
interface RecognitionLike {
  lang: string; interimResults: boolean; continuous: boolean;
  start(): void; stop(): void; abort(): void;
  onstart: (() => void) | null; onend: (() => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onresult: ((e: RecognitionEventLike) => void) | null;
}
type RecognitionCtor = new () => RecognitionLike;

const getCtor = (): RecognitionCtor | null => {
  if (typeof window === 'undefined') return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
};

export function useDictation(onText: (text: string, final: boolean) => void) {
  const supported = !!getCtor();
  const [phase, setPhase] = useState<'idle' | 'starting' | 'listening' | 'stopping'>('idle');
  const [error, setError] = useState<string | null>(null);
  const recRef = useRef<RecognitionLike | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stoppingRef = useRef(false);
  const mountedRef = useRef(true);
  const cbRef = useRef(onText);
  cbRef.current = onText;

  // Detach first: browsers may deliver queued events even after abort().
  const detach = useCallback(() => {
    const rec = recRef.current;
    recRef.current = null;
    stoppingRef.current = false;
    if (timeoutRef.current !== null) clearTimeout(timeoutRef.current);
    timeoutRef.current = null;
    if (rec) rec.onstart = rec.onend = rec.onerror = rec.onresult = null;
    return rec;
  }, []);

  const abort = useCallback(() => {
    const rec = detach();
    try { rec?.abort(); } catch { /* already ended */ }
    if (mountedRef.current) setPhase('idle');
  }, [detach]);

  const stop = useCallback(() => {
    const rec = recRef.current;
    if (!rec) return;
    stoppingRef.current = true;
    setPhase('stopping');
    if (timeoutRef.current !== null) clearTimeout(timeoutRef.current);
    // Allow the recognizer to return its final transcript, but never get stuck.
    timeoutRef.current = setTimeout(() => {
      if (recRef.current === rec) abort();
    }, 5000);
    try { rec.stop(); } catch { abort(); }
  }, [abort]);

  const start = useCallback(() => {
    if (!mountedRef.current) return;
    const Ctor = getCtor();
    if (!Ctor) { setError('Trình duyệt này chưa hỗ trợ nhận dạng giọng nói. Hãy dùng Chrome hoặc Edge, hoặc nhập bằng bàn phím.'); return; }
    if (recRef.current) { stop(); return; }
    if (window.isSecureContext === false) { setError('Micro cần kết nối HTTPS. Hãy mở ứng dụng bằng liên kết bảo mật.'); return; }
    let rec: RecognitionLike;
    try { rec = new Ctor(); } catch { setError('Không khởi động được dịch vụ nhận dạng giọng nói.'); return; }
    const current = () => mountedRef.current && recRef.current === rec;
    const fail = (message: string) => {
      if (!current()) return;
      abort();
      setError(message);
    };
    const armTimeout = (ms: number, message: string) => {
      if (timeoutRef.current !== null) clearTimeout(timeoutRef.current);
      timeoutRef.current = setTimeout(() => fail(message), ms);
    };
    rec.lang = 'vi-VN'; rec.interimResults = true; rec.continuous = false;
    rec.onstart = () => {
      if (!current() || stoppingRef.current) return;
      setPhase('listening');
      armTimeout(60000, 'Đã dừng micro sau một phút. Bạn có thể sửa bản chép lời hoặc bấm micro để nói tiếp.');
    };
    rec.onend = () => {
      if (!current()) return;
      detach();
      setPhase('idle');
    };
    rec.onerror = (e) => {
      if (!current()) return;
      if (e.error === 'aborted') { abort(); return; }
      const messages: Record<string, string> = {
        'not-allowed': 'Chưa được cấp quyền micro. Hãy cho phép micro trong trình duyệt rồi thử lại.',
        'service-not-allowed': 'Trình duyệt không cho phép dịch vụ nhận dạng giọng nói. Hãy kiểm tra quyền hoặc nhập bằng bàn phím.',
        'no-speech': 'Không nghe thấy lời nói. Bấm micro để thử lại.',
        'audio-capture': 'Không tìm thấy micro khả dụng. Hãy kiểm tra thiết bị và ứng dụng đang dùng micro.',
        network: 'Dịch vụ nhận dạng giọng nói mất kết nối. Bản chép lời hiện tại vẫn được giữ; bạn có thể sửa rồi gửi.',
      };
      fail(messages[e.error] || 'Không nhận dạng được giọng nói. Hãy thử lại hoặc nhập bằng bàn phím.');
    };
    rec.onresult = (e) => {
      if (!current()) return;
      // results is cumulative. resultIndex only identifies the first changed
      // result; reading from there loses earlier final phrases.
      const text: string[] = [];
      let final = e.results.length > 0;
      for (let i = 0; i < e.results.length; i += 1) {
        text.push(e.results[i][0].transcript.trim());
        final = final && e.results[i].isFinal;
      }
      cbRef.current(text.filter(Boolean).join(' ').slice(0, 4000), final);
    };
    recRef.current = rec;
    setError(null);
    setPhase('starting');
    armTimeout(20000, 'Chưa khởi động được micro. Hãy kiểm tra quyền truy cập rồi thử lại.');
    try { rec.start(); } catch { fail('Không khởi động được micro.'); }
  }, [abort, detach, stop]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const rec = detach();
      try { rec?.abort(); } catch { /* already ended */ }
    };
  }, [detach]);

  return { supported, phase, listening: phase !== 'idle', error, clearError: () => setError(null), start, stop, abort };
}
