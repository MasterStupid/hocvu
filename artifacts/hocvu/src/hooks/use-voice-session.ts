import { useCallback, useEffect, useRef, useState } from 'react';
import { isLikelySpeakerEcho, type SpeakOptions } from '@/hooks/use-voice';

export type LivePhase = 'off' | 'listening' | 'confirming' | 'thinking' | 'speaking' | 'paused';

export interface SpeakerHandle {
  phase: 'idle' | 'loading' | 'playing';
  lastSpokenRef: { current: { text: string; endedAt: number } };
  unlock: () => void;
  speak: (key: string, text: string, opts?: SpeakOptions) => Promise<void>;
  stop: () => void;
}

interface Options {
  supported: boolean;
  canSend: boolean;
  sending: boolean;
  sessionId: string;
  speaker: SpeakerHandle;
  onRequestListen: () => void;
  onStopListen: () => void;
  onAutoSubmit: (text: string) => Promise<void>;
  confirmDelayMs?: number;
  cooldownMs?: number;
}

/**
 * Hands-free Live Voice Assistant state machine:
 * listen -> echo filter -> brief confirm countdown (editable) -> submit -> speak -> cooldown -> re-listen.
 * Supports immediate barge-in when the student taps Mic while the assistant is speaking.
 */
export function useVoiceSession({
  supported,
  canSend,
  sending,
  sessionId,
  speaker,
  onRequestListen,
  onStopListen,
  onAutoSubmit,
  confirmDelayMs = 1200,
  cooldownMs = 900,
}: Options) {
  const [liveEnabled, setLiveEnabled] = useState(false);
  const [livePaused, setLivePaused] = useState(false);
  const [statusNote, setStatusNote] = useState<string | null>(null);
  const [pendingText, setPendingText] = useState<string | null>(null);

  const liveRef = useRef(liveEnabled);
  liveRef.current = liveEnabled;
  const pausedRef = useRef(livePaused);
  pausedRef.current = livePaused;
  const canSendRef = useRef(canSend);
  canSendRef.current = canSend;
  const confirmTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cooldownTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onRequestListenRef = useRef(onRequestListen);
  onRequestListenRef.current = onRequestListen;
  const onStopListenRef = useRef(onStopListen);
  onStopListenRef.current = onStopListen;
  const onAutoSubmitRef = useRef(onAutoSubmit);
  onAutoSubmitRef.current = onAutoSubmit;

  const clearTimers = useCallback(() => {
    if (confirmTimerRef.current !== null) {
      clearTimeout(confirmTimerRef.current);
      confirmTimerRef.current = null;
    }
    if (cooldownTimerRef.current !== null) {
      clearTimeout(cooldownTimerRef.current);
      cooldownTimerRef.current = null;
    }
  }, []);

  const cancelPendingSend = useCallback(() => {
    if (confirmTimerRef.current !== null) {
      clearTimeout(confirmTimerRef.current);
      confirmTimerRef.current = null;
    }
    setPendingText(null);
    if (liveRef.current) setLivePaused(true);
  }, []);

  const stopLive = useCallback(() => {
    clearTimers();
    setPendingText(null);
    setLiveEnabled(false);
    setLivePaused(false);
    setStatusNote(null);
    onStopListenRef.current();
    speaker.stop();
  }, [clearTimers, speaker]);

  const scheduleNextListen = useCallback((delay = cooldownMs) => {
    clearTimers();
    if (!liveRef.current || pausedRef.current) return;
    cooldownTimerRef.current = setTimeout(() => {
      cooldownTimerRef.current = null;
      if (!liveRef.current || pausedRef.current || !canSendRef.current) return;
      setStatusNote(null);
      onRequestListenRef.current();
    }, delay);
  }, [clearTimers, cooldownMs]);

  const startLive = useCallback(() => {
    if (!supported || !canSendRef.current) return;
    clearTimers();
    speaker.unlock();
    speaker.stop();
    setLiveEnabled(true);
    setLivePaused(false);
    setPendingText(null);
    setStatusNote('Chế độ hội thoại trực tiếp đang bật — hãy nói câu hỏi của bạn.');
    // Start listening on next microtask so React state reflects liveEnabled=true.
    cooldownTimerRef.current = setTimeout(() => {
      cooldownTimerRef.current = null;
      if (liveRef.current && canSendRef.current) onRequestListenRef.current();
    }, 60);
  }, [clearTimers, speaker, supported]);

  const toggleLive = useCallback(() => {
    if (liveRef.current) stopLive();
    else startLive();
  }, [startLive, stopLive]);

  /** Immediate barge-in: interrupt assistant speech and start listening right away. */
  const bargeIn = useCallback(() => {
    clearTimers();
    setPendingText(null);
    speaker.stop();
    if (liveRef.current) {
      setLivePaused(false);
      setStatusNote('Đã ngắt lời — đang nghe câu hỏi mới…');
    }
    onRequestListenRef.current();
  }, [clearTimers, speaker]);

  /** Called when speech recognition produces a final utterance. */
  const handleFinalTranscript = useCallback((text: string, autoSendEnabled: boolean) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    const shouldAuto = liveRef.current || autoSendEnabled;
    if (!shouldAuto) return;

    // Anti-echo guard: ignore transcripts that match what the assistant just read aloud.
    const last = speaker.lastSpokenRef.current;
    if (liveRef.current && last.text && (Date.now() - last.endedAt) < 9000 && isLikelySpeakerEcho(trimmed, last.text)) {
      setLivePaused(true);
      setStatusNote('Đã bỏ qua âm thanh từ loa. Bấm micro để nói tiếp.');
      return;
    }

    clearTimers();
    setPendingText(trimmed);
    setStatusNote(null);
    confirmTimerRef.current = setTimeout(() => {
      confirmTimerRef.current = null;
      setPendingText(null);
      if (canSendRef.current) void onAutoSubmitRef.current(trimmed);
    }, confirmDelayMs);
  }, [clearTimers, confirmDelayMs, speaker.lastSpokenRef]);

  const sendPendingNow = useCallback(() => {
    const text = pendingText;
    if (!text) return;
    clearTimers();
    setPendingText(null);
    if (canSendRef.current) void onAutoSubmitRef.current(text);
  }, [clearTimers, pendingText]);

  /** Speak an answer and re-arm the microphone when Live mode is active. */
  const speakAnswer = useCallback((
    turnKey: string,
    text: string,
    opts?: { autoSpeak: boolean; audioUrl?: string | null },
  ) => {
    if (!liveRef.current && !opts?.autoSpeak) return;
    void speaker.speak(turnKey, text, {
      audioUrl: opts?.audioUrl,
      onComplete: () => {
        if (liveRef.current && !pausedRef.current) {
          scheduleNextListen(cooldownMs);
        }
      },
    });
  }, [cooldownMs, scheduleNextListen, speaker]);

  // Stop Live mode when switching conversations or unmounting.
  const prevSessionRef = useRef(sessionId);
  useEffect(() => {
    if (prevSessionRef.current !== sessionId) {
      prevSessionRef.current = sessionId;
      if (liveRef.current) stopLive();
    }
  }, [sessionId, stopLive]);

  useEffect(() => () => clearTimers(), [clearTimers]);

  const livePhase: LivePhase = !liveEnabled ? 'off'
    : pendingText ? 'confirming'
    : sending ? 'thinking'
    : speaker.phase !== 'idle' ? 'speaking'
    : livePaused ? 'paused'
    : 'listening';

  return {
    liveEnabled,
    livePhase,
    livePaused,
    pendingText,
    statusNote,
    clearStatusNote: () => setStatusNote(null),
    toggleLive,
    startLive,
    stopLive,
    bargeIn,
    handleFinalTranscript,
    cancelPendingSend,
    sendPendingNow,
    speakAnswer,
    scheduleNextListen,
  };
}
