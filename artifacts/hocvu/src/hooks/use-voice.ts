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

  useEffect(() => () => { idRef.current += 1; ctrlRef.current?.abort(); release(); }, []);

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
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
};

export function useDictation(onText: (text: string, final: boolean) => void) {
  const supported = typeof window !== 'undefined' && !!getCtor();
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const recRef = useRef<RecognitionLike | null>(null);
  const cbRef = useRef(onText);
  cbRef.current = onText;

  const stop = useCallback(() => { try { recRef.current?.stop(); } catch { /* ended */ } }, []);
  const abort = useCallback(() => { try { recRef.current?.abort(); } catch { /* ended */ } }, []);

  const start = useCallback(() => {
    const Ctor = getCtor();
    if (!Ctor) { setError('Trình duyệt này chưa hỗ trợ nhận dạng giọng nói. Hãy dùng Chrome hoặc Edge, hoặc nhập bằng bàn phím.'); return; }
    if (recRef.current) { stop(); return; }
    const rec = new Ctor();
    rec.lang = 'vi-VN'; rec.interimResults = true; rec.continuous = false;
    rec.onstart = () => { setListening(true); setError(null); };
    rec.onend = () => { setListening(false); recRef.current = null; };
    rec.onerror = (e) => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') setError('Chưa được cấp quyền micro. Hãy cho phép micro trong trình duyệt rồi thử lại.');
      else if (e.error === 'no-speech') setError('Không nghe thấy lời nói. Bấm micro để thử lại.');
      else if (e.error !== 'aborted') setError('Không nhận dạng được giọng nói. Hãy thử lại hoặc nhập bằng bàn phím.');
    };
    rec.onresult = (e) => {
      let text = ''; let final = false;
      for (let i = e.resultIndex; i < e.results.length; i += 1) { text += e.results[i][0].transcript; final ||= e.results[i].isFinal; }
      cbRef.current(text.trim(), final);
    };
    recRef.current = rec;
    try { rec.start(); } catch { recRef.current = null; setError('Không khởi động được micro.'); }
  }, [stop]);

  useEffect(() => () => { try { recRef.current?.abort(); } catch { /* ignore */ } }, []);

  return { supported, listening, error, clearError: () => setError(null), start, stop, abort };
}
