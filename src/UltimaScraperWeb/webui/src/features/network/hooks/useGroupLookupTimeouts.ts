import { useMutation, useQueries, useQueryClient } from '@tanstack/react-query';

import { getGroupSettings, updateGroupSettings } from '../../../api/network';

const groupSettingsKey = (group: string) => ['proxy-group-settings', group] as const;

/**
 * Each routing group's own guest lookup timeout, inherited by its proxies
 * unless a proxy sets its own. Null means the group uses the network default.
 */
export function useGroupLookupTimeouts(groups: string[]) {
  const queryClient = useQueryClient();
  const results = useQueries({
    queries: groups.map((group) => ({
      queryKey: groupSettingsKey(group),
      queryFn: () => getGroupSettings(group),
      staleTime: 60_000,
    })),
  });

  const timeouts: Record<string, number | null> = {};
  groups.forEach((group, index) => {
    timeouts[group] = results[index]?.data?.guest_lookup_timeout ?? null;
  });

  const mutation = useMutation({
    mutationFn: ({ group, timeout }: { group: string; timeout: number | null }) =>
      updateGroupSettings(group, { guest_lookup_timeout: timeout }),
    onSuccess: (data, { group }) => {
      queryClient.setQueryData(groupSettingsKey(group), {
        group,
        guest_lookup_timeout: data.guest_lookup_timeout ?? null,
      });
    },
  });

  return {
    timeouts,
    saveTimeout: (group: string, timeout: number | null) => mutation.mutateAsync({ group, timeout }),
    savingGroup: mutation.isPending ? mutation.variables?.group ?? null : null,
    saveError: mutation.error,
  };
}
