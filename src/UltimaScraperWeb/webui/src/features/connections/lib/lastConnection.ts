import type { BackendConnection } from '../../../api/webui';

const LAST_CONNECTION_KEY = 'usr_webui_last_connection';

export function rememberConnection(id: string): void {
  try {
    localStorage.setItem(LAST_CONNECTION_KEY, id);
  } catch {
    // A private window without storage just starts at the default backend.
  }
}

function lastConnection(): string | null {
  try {
    return localStorage.getItem(LAST_CONNECTION_KEY);
  } catch {
    return null;
  }
}

/**
 * The backend to open: the last one used, else the default (a member of the
 * WebUI's main cluster, when it has one), else the first. A last-used backend
 * outside the main cluster is not reopened.
 */
export function pickConnection(
  connections: BackendConnection[],
  defaultConnection: string | null,
  mainConnections: string[] = [],
): BackendConnection | null {
  const ids = new Set(connections.map((connection) => connection.id));
  const last = lastConnection();
  const lastAllowed = mainConnections.length === 0 || (last !== null && mainConnections.includes(last));
  const preferred = [lastAllowed ? last : null, defaultConnection].find((id) => id && ids.has(id));
  return connections.find((connection) => connection.id === preferred) ?? connections[0] ?? null;
}
