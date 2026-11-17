import { useCallback, useEffect, useRef, useState } from 'react';
import { api, apiUrl, describeError } from '@/lib/api';
import { speechText } from '@/lib/format';

/* ---------- Text to speech via POST /api/tts ---------- */
export function useSpeaker(voice: string, rate: string) {
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [phase, setPhase] = useState<'idle' | 'loading' | 'playing'>('idle');
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

  const stop = useCallback(() => {
    idRef.current += 1;
    ctrlRef.current?.abort();
    ctrlRef.current = null;
    release();
    setActiveKey(null);
    setPhase('idle');
  }, []);

  const speak = useCallback(async (key: string, text: string) => {
    if (!mountedRef.current) return;
    stop();
    const id = idRef.current;
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;
    setActiveKey(key); setPhase('loading'); setError(null);
    try {
      const { audio_url } = await api.tts(speechText(text).slice(0, 4000), voice, rate, ctrl.signal);
      if (id !== idRef.current) return;
      const audio = new Audio(apiUrl(audio_url));
      audioRef.current = audio;
      audio.onended = () => { if (id === idRef.current) { release(); setActiveKey(null); setPhase('idle'); } };
      audio.onerror = () => { if (id === idRef.current) { release(); setActiveKey(null); setPhase('idle'); setError('Không phát được tệp âm thanh.'); } };
      await audio.play();
      if (id === idRef.current) setPhase('playing');
    } catch (e) {
      if (id !== idRef.current) return;
      release(); setActiveKey(null); setPhase('idle');
      if (e instanceof DOMException && e.name === 'AbortError') return;
      if (e instanceof DOMException && e.name === 'NotAllowedError') setError('Trình duyệt chặn tự phát âm thanh. Hãy bấm Nghe để phát.');
      else setError(describeError(e, 'Không tạo được giọng đọc.'));
    }
  }, [rate, stop, voice]);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; idRef.current += 1; ctrlRef.current?.abort(); release(); };
  }, []);

  return { activeKey, phase, error, clearError: () => setError(null), speak, stop };
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
