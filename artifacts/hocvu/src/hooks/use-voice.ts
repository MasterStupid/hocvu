import { useCallback, useEffect, useRef, useState } from 'react';
import { api, apiUrl, describeError } from '@/lib/api';
import { speechText, splitSpeechChunks } from '@/lib/format';

// 44-byte silent WAV used to unlock mobile/Safari HTMLAudioElement autoplay inside a user gesture.
const SILENT_WAV = 'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA';

function speechWords(value: string): string[] {
  return speechText(value)
    .toLocaleLowerCase('vi-VN')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .match(/[a-zđ0-9]+/g) || [];
}

/** Filters out transcripts that are mostly echo from the assistant's own speaker output. */
export function isLikelySpeakerEcho(heard: string, lastAssistantSpeech: string): boolean {
  const h = speechWords(heard);
  const s = speechWords(lastAssistantSpeech);
  if (h.length < 4 || !s.length) return false;
  const spokenSet = new Set(s);
  const uniqueHeard = new Set(h);
  let shared = 0;
  uniqueHeard.forEach((word) => { if (spokenSet.has(word)) shared += 1; });
  return shared / uniqueHeard.size >= 0.78;
}

function preferredVietnameseVoice(): SpeechSynthesisVoice | undefined {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) return undefined;
  const voices = window.speechSynthesis.getVoices();
  return voices.find((v) => /^vi(-|_)/i.test(v.lang) && /hoaimy|namminh|vietnamese|việt/i.test(v.name))
    || voices.find((v) => /^vi(-|_)/i.test(v.lang));
}

function rateToNumber(rate: string): number {
  const m = /^([+-]?\d+)%$/.exec(rate.trim());
  if (!m) return 1;
  return Math.max(0.6, Math.min(1.6, 1 + Number(m[1]) / 100));
}

export interface SpeakOptions {
  /** Pre-generated audio URL from /api/ask (skips extra TTS round-trip). */
  audioUrl?: string | null;
  onComplete?: () => void;
}

/* ---------- Text to speech (streaming Edge-TTS + browser speechSynthesis fallback) ---------- */
export function useSpeaker(voice: string, rate: string) {
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [phase, setPhase] = useState<'idle' | 'loading' | 'playing'>('idle');
  const [error, setError] = useState<string | null>(null);
  const [usingFallback, setUsingFallback] = useState(false);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const unlockedAudioRef = useRef<HTMLAudioElement | null>(null);
  const objectUrlsRef = useRef<string[]>([]);
  const ctrlRef = useRef<AbortController | null>(null);
  const idRef = useRef(0);
  const mountedRef = useRef(true);
  const lastSpokenRef = useRef<{ text: string; endedAt: number }>({ text: '', endedAt: 0 });

  const revokeUrls = () => {
    const urls = objectUrlsRef.current;
    objectUrlsRef.current = [];
    for (const u of urls) {
      try { URL.revokeObjectURL(u); } catch { /* ignore */ }
    }
  };

  const release = () => {
    const a = audioRef.current;
    audioRef.current = null;
    if (a) {
      a.onended = null;
      a.onerror = null;
      a.pause();
      // Keep unlocked singleton element reusable without discarding its user activation.
      if (a !== unlockedAudioRef.current) {
        a.removeAttribute('src');
        a.load();
      }
    }
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      try { window.speechSynthesis.cancel(); } catch { /* ignore */ }
    }
    revokeUrls();
  };

  /** Call synchronously inside a click/tap handler (Live, Mic, Send) so autoplay isn't blocked later. */
  const unlock = useCallback(() => {
    if (typeof window === 'undefined' || typeof Audio === 'undefined') return;
    try {
      let el = unlockedAudioRef.current;
      if (!el) {
        el = new Audio();
        unlockedAudioRef.current = el;
      }
      el.src = SILENT_WAV;
      el.muted = true;
      const p = el.play();
      if (p && typeof p.then === 'function') {
        p.then(() => { el!.pause(); el!.muted = false; }).catch(() => { el!.muted = false; });
      } else {
        el.muted = false;
      }
    } catch {
      /* ignore environments without HTMLMediaElement play */
    }
  }, []);

  const stop = useCallback(() => {
    idRef.current += 1;
    ctrlRef.current?.abort();
    ctrlRef.current = null;
    release();
    setActiveKey(null);
    setPhase('idle');
    setUsingFallback(false);
  }, []);

  const speakBrowserFallback = useCallback((spoken: string, id: number): Promise<boolean> => {
    return new Promise((resolve) => {
      if (id !== idRef.current || typeof window === 'undefined' || !('speechSynthesis' in window) || typeof SpeechSynthesisUtterance === 'undefined') {
        resolve(false);
        return;
      }
      const run = (retried: boolean) => {
        if (id !== idRef.current) { resolve(false); return; }
        const voices = window.speechSynthesis.getVoices();
        if (!voices.length && !retried) {
          setTimeout(() => run(true), 160);
          return;
        }
        window.speechSynthesis.cancel();
        const u = new SpeechSynthesisUtterance(spoken);
        u.lang = 'vi-VN';
        u.rate = rateToNumber(rate);
        const v = preferredVietnameseVoice();
        if (v) u.voice = v;
        u.onstart = () => { if (id === idRef.current) { setUsingFallback(true); setPhase('playing'); } };
        u.onend = () => resolve(true);
        u.onerror = () => resolve(false);
        setUsingFallback(true);
        setPhase('playing');
        window.speechSynthesis.speak(u);
      };
      run(false);
    });
  }, [rate]);

  const fetchAudioSource = useCallback(async (chunk: string, signal: AbortSignal): Promise<string> => {
    if (typeof api.ttsStream === 'function' && typeof URL.createObjectURL === 'function') {
      try {
        const blob = await api.ttsStream(chunk, voice, rate, signal);
        const url = URL.createObjectURL(blob);
        objectUrlsRef.current.push(url);
        return url;
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') throw err;
        // Fall through to legacy POST /api/tts if /api/tts/stream is unavailable.
      }
    }
    const { audio_url } = await api.tts(chunk, voice, rate, signal);
    return apiUrl(audio_url);
  }, [rate, voice]);

  const playUrl = useCallback((src: string, id: number): Promise<void> => {
    return new Promise((resolve, reject) => {
      if (id !== idRef.current) { resolve(); return; }
      const el = unlockedAudioRef.current || new Audio();
      audioRef.current = el;
      el.onended = () => { if (id === idRef.current) resolve(); };
      el.onerror = () => { if (id === idRef.current) reject(new Error('Không phát được tệp âm thanh.')); };
      el.src = src;
      const playPromise = el.play();
      if (playPromise && typeof playPromise.then === 'function') {
        playPromise.then(() => {
          if (id === idRef.current) setPhase('playing');
        }).catch((err) => reject(err));
      } else if (id === idRef.current) {
        setPhase('playing');
      }
    });
  }, []);

  const speak = useCallback(async (key: string, text: string, opts?: SpeakOptions) => {
    if (!mountedRef.current) return;
    stop();
    const id = idRef.current;
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;
    const spoken = speechText(text).slice(0, 4000);
    if (!spoken) return;
    setActiveKey(key); setPhase('loading'); setError(null); setUsingFallback(false);

    const finish = (completedNormally: boolean) => {
      if (id !== idRef.current) return;
      release();
      setActiveKey(null);
      setPhase('idle');
      setUsingFallback(false);
      if (completedNormally) {
        lastSpokenRef.current = { text: spoken, endedAt: Date.now() };
        opts?.onComplete?.();
      }
    };

    try {
      if (opts?.audioUrl) {
        await playUrl(apiUrl(opts.audioUrl), id);
        finish(true);
        return;
      }
      const chunks = splitSpeechChunks(spoken, 260);
      let nextPromise: Promise<string> | null = fetchAudioSource(chunks[0], ctrl.signal);
      for (let i = 0; i < chunks.length; i += 1) {
        const src = await nextPromise!;
        if (id !== idRef.current) return;
        // Prefetch the next sentence while the current one plays.
        nextPromise = i + 1 < chunks.length ? fetchAudioSource(chunks[i + 1], ctrl.signal) : null;
        await playUrl(src, id);
        if (id !== idRef.current) return;
      }
      finish(true);
    } catch (e) {
      if (id !== idRef.current) return;
      if (e instanceof DOMException && e.name === 'AbortError') { finish(false); return; }
      if (e instanceof DOMException && e.name === 'NotAllowedError') {
        finish(false);
        setError('Trình duyệt chặn tự phát âm thanh. Hãy bấm Nghe để phát.');
        return;
      }
      // Graceful fallback to browser speechSynthesis if Edge-TTS fails.
      const ok = await speakBrowserFallback(spoken, id);
      if (id !== idRef.current) return;
      if (ok) {
        finish(true);
      } else {
        finish(false);
        setError(describeError(e, 'Không tạo được giọng đọc.'));
      }
    }
  }, [fetchAudioSource, playUrl, speakBrowserFallback, stop]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      idRef.current += 1;
      ctrlRef.current?.abort();
      release();
    };
  }, []);

  return {
    activeKey, phase, error, usingFallback,
    lastSpokenRef,
    clearError: () => setError(null),
    unlock, speak, stop,
  };
}

/* ---------- Speech recognition (Web Speech API + optional MediaRecorder -> /api/stt fallback) ---------- */
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

const canRecordAudio = (): boolean => {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return false;
  return typeof navigator.mediaDevices?.getUserMedia === 'function' && typeof MediaRecorder !== 'undefined';
};

export interface DictationOptions {
  /** Enable server-side /api/stt fallback when Web Speech API is unavailable. */
  sttFallback?: boolean;
}

export function useDictation(onText: (text: string, final: boolean) => void, opts?: DictationOptions) {
  const hasNative = !!getCtor();
  const useServerFallback = !hasNative && Boolean(opts?.sttFallback) && canRecordAudio();
  const mode: 'browser' | 'server' | 'none' = hasNative ? 'browser' : useServerFallback ? 'server' : 'none';
  const supported = mode !== 'none';

  const [phase, setPhase] = useState<'idle' | 'starting' | 'listening' | 'stopping'>('idle');
  const [error, setError] = useState<string | null>(null);
  const recRef = useRef<RecognitionLike | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const sttCtrlRef = useRef<AbortController | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stoppingRef = useRef(false);
  const mountedRef = useRef(true);
  const cbRef = useRef(onText);
  cbRef.current = onText;

  const stopMediaTracks = useCallback(() => {
    const s = streamRef.current;
    streamRef.current = null;
    if (s) s.getTracks().forEach((t) => { try { t.stop(); } catch { /* ignore */ } });
  }, []);

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
    sttCtrlRef.current?.abort();
    sttCtrlRef.current = null;
    const mr = recorderRef.current;
    recorderRef.current = null;
    if (mr) {
      mr.onstop = null;
      mr.onerror = null;
      try { if (mr.state !== 'inactive') mr.stop(); } catch { /* ignore */ }
    }
    stopMediaTracks();
    if (mountedRef.current) setPhase('idle');
  }, [detach, stopMediaTracks]);

  const stop = useCallback(() => {
    const mr = recorderRef.current;
    if (mr && mr.state !== 'inactive') {
      stoppingRef.current = true;
      setPhase('stopping');
      if (timeoutRef.current !== null) clearTimeout(timeoutRef.current);
      try { mr.stop(); } catch { abort(); }
      return;
    }
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

  const startServerFallback = useCallback(async () => {
    if (window.isSecureContext === false) {
      setError('Micro cần kết nối HTTPS (hoặc localhost). Hãy mở ứng dụng bằng liên kết bảo mật.');
      return;
    }
    setError(null);
    setPhase('starting');
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!mountedRef.current) { stream.getTracks().forEach((t) => t.stop()); return; }
      streamRef.current = stream;
      const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/mp4') ? 'audio/mp4' : 'audio/webm';
      const chunks: Blob[] = [];
      const mr = new MediaRecorder(stream, MediaRecorder.isTypeSupported(mime) ? { mimeType: mime } : undefined);
      recorderRef.current = mr;
      mr.ondataavailable = (ev) => { if (ev.data.size > 0) chunks.push(ev.data); };
      mr.onerror = () => {
        abort();
        setError('Không thể ghi âm từ micro. Hãy kiểm tra quyền thiết bị.');
      };
      mr.onstop = async () => {
        recorderRef.current = null;
        stopMediaTracks();
        if (!mountedRef.current) return;
        const blob = new Blob(chunks, { type: mr.mimeType || 'audio/webm' });
        if (!blob.size) { setPhase('idle'); return; }
        const ctrl = new AbortController();
        sttCtrlRef.current = ctrl;
        setPhase('stopping');
        try {
          const ext = (mr.mimeType || '').includes('mp4') ? 'm4a' : 'webm';
          const res = await api.stt(blob, `voice.${ext}`, ctrl.signal);
          if (mountedRef.current && res.text.trim()) cbRef.current(res.text.trim().slice(0, 4000), true);
        } catch (err) {
          if (!(err instanceof DOMException && err.name === 'AbortError') && mountedRef.current) {
            setError(describeError(err, 'Không nhận dạng được đoạn ghi âm.'));
          }
        } finally {
          sttCtrlRef.current = null;
          if (mountedRef.current) setPhase('idle');
        }
      };
      mr.start();
      setPhase('listening');
      timeoutRef.current = setTimeout(() => {
        if (recorderRef.current === mr && mr.state !== 'inactive') mr.stop();
      }, 25000);
    } catch {
      abort();
      setError('Chưa được cấp quyền micro. Hãy cho phép micro trong trình duyệt rồi thử lại.');
    }
  }, [abort, stopMediaTracks]);

  const start = useCallback(() => {
    if (!mountedRef.current) return;
    if (recRef.current || recorderRef.current) { stop(); return; }
    const Ctor = getCtor();
    if (!Ctor) {
      if (useServerFallback) { void startServerFallback(); return; }
      setError('Trình duyệt này chưa hỗ trợ nhận dạng giọng nói. Hãy dùng Chrome hoặc Edge, hoặc nhập bằng bàn phím.');
      return;
    }
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
  }, [abort, detach, startServerFallback, stop, useServerFallback]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      const rec = detach();
      try { rec?.abort(); } catch { /* already ended */ }
      sttCtrlRef.current?.abort();
      const mr = recorderRef.current;
      if (mr && mr.state !== 'inactive') { try { mr.stop(); } catch { /* ignore */ } }
      stopMediaTracks();
    };
  }, [detach, stopMediaTracks]);

  return { supported, mode, phase, listening: phase !== 'idle', error, clearError: () => setError(null), start, stop, abort };
}
