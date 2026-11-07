import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { getSettings, updateSettings } from '../../../api/settings';
import type {
  DownloadConcurrencySettings,
  SettingsUpdate,
} from '../../../api/types/settings';

export type DownloadLimits = Pick<
  DownloadConcurrencySettings,
  'max_concurrency' | 'per_domain_concurrency' | 'head_concurrency'
>;

const settingsKey = ['settings'] as const;

/**
 * The network's download limits, which every proxy without download settings
 * of its own uses. Saving sends only these fields; the rest are kept.
 */
export function useNetworkDownloadLimits() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: settingsKey, queryFn: getSettings });

  const mutation = useMutation({
    mutationFn: (limits: DownloadLimits) =>
      updateSettings({
        network: { downloads: limits },
        expected_version: query.data?.config_version ?? undefined,
      } as unknown as SettingsUpdate),
    onSuccess: (settings) => {
      queryClient.setQueryData(settingsKey, settings);
    },
    onError: () => {
      // A conflict means another save came first: load its version.
      void queryClient.invalidateQueries({ queryKey: settingsKey });
    },
  });

  const downloads = query.data?.network?.downloads;
  return {
    limits: downloads
      ? {
          max_concurrency: downloads.max_concurrency,
          per_domain_concurrency: downloads.per_domain_concurrency,
          head_concurrency: downloads.head_concurrency,
        }
      : null,
    isLoading: query.isLoading,
    loadError: query.error,
    save: (limits: DownloadLimits) => mutation.mutateAsync(limits),
    isSaving: mutation.isPending,
    saveError: mutation.error,
  };
}
