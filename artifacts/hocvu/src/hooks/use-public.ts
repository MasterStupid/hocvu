import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

export const healthKey = ['health'] as const;
export const catalogKey = ['catalog'] as const;
export const suggestionsKey = ['suggestions'] as const;

export const useHealth = () =>
  useQuery({ queryKey: healthKey, queryFn: ({ signal }) => api.health(signal), refetchInterval: 60_000, retry: 1 });
export const useCatalog = () =>
  useQuery({ queryKey: catalogKey, queryFn: ({ signal }) => api.catalog(signal), retry: 1 });
export const useCatalogDetail = (rid: string | null) =>
  useQuery({
    queryKey: ['catalog-detail', rid],
    queryFn: ({ signal }) => api.catalogDetail(rid as string, signal),
    enabled: Boolean(rid),
    retry: 1,
  });
export const useSuggestions = () =>
  useQuery({ queryKey: suggestionsKey, queryFn: ({ signal }) => api.suggestions(signal), staleTime: 10 * 60_000, retry: 1 });
