import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { ADMIN_KEY } from '@/lib/admin-auth';
import { catalogKey, healthKey } from '@/hooks/use-public';

export const adminDocsKey = [...ADMIN_KEY, 'documents'] as const;
export const adminStorageKey = [...ADMIN_KEY, 'storage'] as const;

export function useAdminDocuments(token: string | null) {
  return useQuery({
    queryKey: adminDocsKey,
    queryFn: ({ signal }) => api.documents(token as string, signal),
    enabled: !!token,
    retry: false,
  });
}

export function useStorageStatus(token: string | null) {
  return useQuery({
    queryKey: adminStorageKey,
    queryFn: ({ signal }) => api.storage(token as string, signal),
    enabled: !!token,
    retry: false,
  });
}

export function useDocumentText(token: string | null, id: string | null) {
  return useQuery({
    queryKey: [...ADMIN_KEY, 'text', id],
    queryFn: ({ signal }) => api.documentText(token as string, id as string, signal),
    enabled: !!token && !!id,
    retry: false,
  });
}

/** Refetch everything a document mutation can change. Resolves to an error message if the
 * admin list could not be reloaded, so callers can distinguish "committed but stale view". */
export function useRefreshAfterCommit() {
  const qc = useQueryClient();
  return async (): Promise<string | null> => {
    void qc.invalidateQueries({ queryKey: catalogKey });
    void qc.invalidateQueries({ queryKey: healthKey });
    void qc.invalidateQueries({ queryKey: adminStorageKey });
    await qc.refetchQueries({ queryKey: adminDocsKey, exact: true });
    const state = qc.getQueryState(adminDocsKey);
    return state?.status === 'error' && state.error ? (state.error as Error).message : null;
  };
}
