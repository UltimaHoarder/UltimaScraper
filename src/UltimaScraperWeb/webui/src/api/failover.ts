/**
 * Which backend last answered for the open one. The WebUI server sends reads of
 * a cluster's shared data to another member while the open backend is
 * unreachable, and names it in X-USR-Served-By.
 */
let servedBy: string | null = null;
const listeners = new Set<() => void>();

export function reportServedBy(connectionId: string | null): void {
  if (connectionId === servedBy) return;
  servedBy = connectionId;
  for (const listener of listeners) listener();
}

export function getServedBy(): string | null {
  return servedBy;
}

export function subscribeToFailover(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
