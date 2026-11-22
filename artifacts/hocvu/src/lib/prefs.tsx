import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

// Only non-sensitive presentation preferences are persisted here.
export type ThemePref = 'light' | 'dark' | 'system';
export const VOICES = [
  { id: 'vi-VN-HoaiMyNeural', label: 'Hoài My', note: 'Giọng nữ, miền Bắc' },
  { id: 'vi-VN-NamMinhNeural', label: 'Nam Minh', note: 'Giọng nam, miền Bắc' },
] as const;
export const RATES = [
  { id: '-15%', label: 'Chậm' }, { id: '+0%', label: 'Bình thường' }, { id: '+15%', label: 'Nhanh' },
] as const;

interface Prefs {
  theme: ThemePref;
  aiEnabled: boolean;
  voice: string;
  rate: string;
  autoSpeak: boolean;
  autoSendVoice: boolean;
}
interface PrefsCtx extends Prefs {
  resolvedTheme: 'light' | 'dark';
  set: <K extends keyof Prefs>(key: K, value: Prefs[K]) => void;
}

const KEYS: Record<keyof Prefs, string> = {
  theme: 'hv_theme', aiEnabled: 'hv_ai_enabled', voice: 'hv_voice', rate: 'hv_voice_rate', autoSpeak: 'hv_auto_speak', autoSendVoice: 'hv_auto_send_voice',
};
const read = (k: string) => { try { return localStorage.getItem(k); } catch { return null; } };

function load(): Prefs {
  const theme = read(KEYS.theme);
  const voice = read(KEYS.voice);
  const rate = read(KEYS.rate);
  return {
    theme: theme === 'dark' || theme === 'system' ? theme : 'light',
    aiEnabled: read(KEYS.aiEnabled) === 'true',
    voice: VOICES.some((v) => v.id === voice) ? (voice as string) : VOICES[0].id,
    rate: RATES.some((r) => r.id === rate) ? (rate as string) : '+0%',
    autoSpeak: read(KEYS.autoSpeak) === 'true',
    autoSendVoice: read(KEYS.autoSendVoice) === 'true',
  };
}

const Ctx = createContext<PrefsCtx | null>(null);

export function PrefsProvider({ children }: { children: ReactNode }) {
  const [prefs, setPrefs] = useState<Prefs>(load);
  const [systemDark, setSystemDark] = useState(() => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false);

  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (!mq) return;
    const fn = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener('change', fn);
    return () => mq.removeEventListener('change', fn);
  }, []);

  const resolvedTheme = prefs.theme === 'system' ? (systemDark ? 'dark' : 'light') : prefs.theme;
  useEffect(() => {
    document.documentElement.classList.toggle('dark', resolvedTheme === 'dark');
    document.documentElement.style.colorScheme = resolvedTheme;
  }, [resolvedTheme]);

  // Keep tabs in sync when another tab changes a preference.
  useEffect(() => {
    const fn = (e: StorageEvent) => { if (e.key && Object.values(KEYS).includes(e.key)) setPrefs(load()); };
    window.addEventListener('storage', fn);
    return () => window.removeEventListener('storage', fn);
  }, []);

  const set = useCallback(<K extends keyof Prefs>(key: K, value: Prefs[K]) => {
    setPrefs((p) => ({ ...p, [key]: value }));
    try { localStorage.setItem(KEYS[key], String(value)); } catch { /* ignore */ }
  }, []);

  const value = useMemo(() => ({ ...prefs, resolvedTheme, set }), [prefs, resolvedTheme, set]) as PrefsCtx;
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function usePrefs(): PrefsCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error('usePrefs outside PrefsProvider');
  return v;
}
