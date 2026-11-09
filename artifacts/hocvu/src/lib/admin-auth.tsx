import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

// The admin password lives ONLY in React memory. A reload signs the user out.
interface AdminCtx {
  token: string | null;
  signIn: (password: string) => Promise<void>;
  signOut: () => void;
}
const Ctx = createContext<AdminCtx | null>(null);
export const ADMIN_KEY = ['admin'] as const;

export function AdminAuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [token, setToken] = useState<string | null>(null);

  const signIn = useCallback(async (password: string) => {
    const docs = await api.documents(password);
    qc.setQueryData([...ADMIN_KEY, 'documents'], docs);
    setToken(password);
  }, [qc]);

  const signOut = useCallback(() => {
    qc.cancelQueries({ queryKey: ADMIN_KEY });
    qc.removeQueries({ queryKey: ADMIN_KEY });
    setToken(null);
  }, [qc]);

  const value = useMemo(() => ({ token, signIn, signOut }), [token, signIn, signOut]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAdminAuth(): AdminCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAdminAuth outside provider');
  return v;
}
