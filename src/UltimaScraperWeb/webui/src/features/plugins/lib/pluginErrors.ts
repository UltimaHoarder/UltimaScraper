/** Prefer the API's detail message for plugin operations. */
export function pluginError(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === 'string' ? detail : error instanceof Error ? error.message : 'Plugin operation failed.';
}
