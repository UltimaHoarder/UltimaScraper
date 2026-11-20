import type { ApiMethodSpec } from '../../../api/apiRequests';

/** The methods `site` can run, in catalogue order. */
export function methodsForSite(
  methods: Record<string, ApiMethodSpec>,
  site: string,
): Record<string, ApiMethodSpec> {
  return Object.fromEntries(
    Object.entries(methods).filter(([, spec]) => !spec.sites || spec.sites.includes(site)),
  );
}
