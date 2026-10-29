/** The WebUI server's own API: sign-in and backend connections. */

export interface WebUISession {
  authenticated: boolean;
  password_set: boolean;
  /** No password yet, and this browser may set it without the setup code. */
  can_claim: boolean;
  /** Where the app opens: a member of the main cluster, else the deployment's connection. */
  default_connection: string | null;
  /** The main cluster's connections; a last-used one outside them is not reopened. */
  main_connections?: string[];
}

export interface WebUIClientSession {
  id: string;
  ip_address: string;
  user_agent: string;
  device_info: string;
  is_local: boolean;
  created_at: number;
  last_seen: number;
  is_current: boolean;
}

export interface BackendConnection {
  id: string;
  name: string;
  base_url: string;
  tls_verify: boolean;
  /** Configured by the deployment, so it cannot be edited here. */
  managed: boolean;
  has_token: boolean;
  /** Whether this backend's native plugins may run code in the WebUI page. */
  trust_plugins: boolean;
}

export interface BackendConnectionInput {
  name: string;
  base_url: string;
  /** Omit to keep the stored token when editing. */
  token?: string | null;
  tls_verify: boolean;
}

export interface BackendConnectionTest {
  reachable: boolean;
  authenticated: boolean;
  message: string;
  latency_ms: number | null;
}

export interface BackendIdentity {
  backend_id: string;
  instance: string;
  cluster_id: string | null;
  api_url: string | null;
  version: string;
  api_version: number;
}

export interface ClusterMember {
  connection_id: string;
  name: string;
  reachable: boolean;
  /** The last identity the backend reported; kept while it is unreachable. */
  identity: BackendIdentity | null;
  seen_at: number | null;
}

export interface SuggestedClusterMember {
  backend_id: string;
  hostname: string;
  status: string;
  last_seen: string;
  /** Null when that backend does not advertise USR_PUBLIC_API_URL. */
  api_url: string | null;
}

export interface BackendCluster {
  cluster_id: string;
  /** What this WebUI calls the cluster. */
  name?: string;
  connection_ids: string[];
  /** Live members of this cluster that have no connection here yet. */
  suggestions: SuggestedClusterMember[];
  /** Ids reported by more than one running backend. */
  conflicting_backend_ids: string[];
}

export interface BackendClusters {
  members: ClusterMember[];
  clusters: BackendCluster[];
  /** The cluster this WebUI opens on. */
  main_cluster_id?: string | null;
}

const BASE = '/webui/api/v1';

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    credentials: 'same-origin',
    headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...init.headers },
  });
  if (!response.ok) {
    let detail = `Request failed (HTTP ${response.status}).`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      // Keep the status message.
    }
    throw new Error(detail);
  }
  return (response.status === 204 ? undefined : await response.json()) as T;
}

/** The shortest WebUI password the server accepts. */
export const MIN_WEBUI_PASSWORD_LENGTH = 12;

export const getWebUISession = () => request<WebUISession>('/session');

export const claimWebUI = (password: string, code?: string) =>
  request<void>('/session/claim', { method: 'POST', body: JSON.stringify({ password, code: code || null }) });

export const signInToWebUI = (password: string) =>
  request<void>('/session/login', { method: 'POST', body: JSON.stringify({ password }) });

export const changeWebUIPassword = (currentPassword: string, newPassword: string) =>
  request<void>('/session/password', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });

export const revokeAllWebUISessions = () =>
  request<void>('/session/revoke-all', { method: 'POST' });

export const listWebUIClients = () => request<WebUIClientSession[]>('/clients');

export const revokeWebUIClient = (id: string) =>
  request<void>(`/clients/${encodeURIComponent(id)}`, { method: 'DELETE' });

export const signOutOfWebUI = () => request<void>('/session/logout', { method: 'POST' });

export const listConnections = () => request<BackendConnection[]>('/connections');

/** Asks every backend who it is; slower than listConnections. */
export const listClusters = () => request<BackendClusters>('/clusters');

export const addConnection = (input: BackendConnectionInput) =>
  request<BackendConnection>('/connections', { method: 'POST', body: JSON.stringify(input) });

export const updateConnection = (id: string, input: BackendConnectionInput) =>
  request<BackendConnection>(`/connections/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(input),
  });

export const setPluginTrust = (id: string, trusted: boolean) =>
  request<BackendConnection>(`/connections/${encodeURIComponent(id)}/plugin-trust`, {
    method: 'PUT',
    body: JSON.stringify({ trusted }),
  });

export const removeConnection = (id: string) =>
  request<void>(`/connections/${encodeURIComponent(id)}`, { method: 'DELETE' });

export const testConnection = (id: string) =>
  request<BackendConnectionTest>(`/connections/${encodeURIComponent(id)}/test`, { method: 'POST' });

export interface ConnectionTicket {
  ticket: string;
  /** The name and address the ticket gives another WebUI. */
  name: string;
  base_url: string;
  /** Why that address may not work on another WebUI, when it may not. */
  warning: string | null;
}

export const getConnectionTicket = (id: string) =>
  request<ConnectionTicket>(`/connections/${encodeURIComponent(id)}/ticket`);

export const parseConnectionTicket = (ticket: string) =>
  request<{ name: string; base_url: string; token: string | null; tls_verify: boolean; cluster_id?: string | null }>(
    '/connections/parse-ticket',
    {
      method: 'POST',
      body: JSON.stringify({ ticket }),
    },
  );

/** The page for a backend connection: the whole app runs under / for local default, or /b/{connection}/ for remotes. */
export const connectionHome = (id: string) => (id === 'default' ? '/' : `/b/${encodeURIComponent(id)}/`);

// ---- Installer ---------------------------------------------------------

export interface LocalRelease {
  version: string;
  architecture: string;
  names: string[];
}

export interface InstallEnvironment {
  /** This WebUI's release, suggested for a registry install. */
  version: string;
  /** Whether this WebUI can install onto its own machine without SSH. */
  local_available: boolean;
  in_container: boolean;
  /** Whether images can be copied from this server's Docker. */
  copy_available: boolean;
  releases: LocalRelease[];
}

export interface HostKey {
  algorithm: string;
  fingerprint: string;
  key: string;
}

export interface InstallTarget {
  kind: 'local' | 'ssh';
  host?: string;
  port?: number;
  username?: string;
  password?: string;
  private_key?: string;
  host_key?: string;
  sudo_password?: string;
}

export type ComponentMode = 'install' | 'none';
export type StoreMode = 'install' | 'existing' | 'none';
export type WebUIMode = 'reuse' | 'install';

export interface ComponentSelection {
  backend: ComponentMode;
  worker: ComponentMode;
  postgres: StoreMode;
  redis: StoreMode;
  webui: WebUIMode;
}

export interface InstallComponents {
  backend: boolean | ComponentMode;
  worker: boolean | ComponentMode;
  postgres: boolean | StoreMode;
  redis: boolean | StoreMode;
  webui: boolean | WebUIMode;
}

export interface InstallDatabaseInput {
  host: string;
  port: number;
  name: string;
  user: string;
  password?: string;
}

export interface InstallRequest {
  name: string;
  target: InstallTarget;
  components: InstallComponents | ComponentSelection;
  install_dir: string;
  image_source: 'copy' | 'target' | 'registry';
  version: string;
  image_prefix?: string;
  /** Install Docker from the distribution's packages when the host lacks it. */
  install_docker?: boolean;
  database_url?: string;
  database?: InstallDatabaseInput;
  postgres_port?: number;
  redis_host?: string;
  redis_port?: number;
  redis_password?: string;
  join_connection_id?: string | null;
  /** Serve the backend over HTTPS for other machines (WebUIs that join its cluster). */
  share_backend?: boolean;
}

export interface DetectedServiceInfo {
  /** Reachable from this host's containers (listening, or a published container port). */
  detected: boolean;
  host?: string;
  port?: number;
  listening?: boolean;
  container?: string | null;
  /** Containers that keep the port on their own network, so cannot be reused. */
  unreachable_containers?: string[];
}

export interface ExistingInstallInfo {
  project: string;
  version: string;
  install_dir?: string;
  components?: string[];
  image_source?: 'copy' | 'target' | 'registry';
  image_prefix?: string;
  backend_port?: number;
  web_port?: number;
  deployment_id?: string | null;
}

export interface HostFacts {
  architecture: string;
  os_name: string;
  user: string;
  home: string;
  hostname: string;
  docker_version: string | null;
  compose_version: string | null;
  docker_needs_sudo: boolean;
  sudo_mode: 'none' | 'passwordless' | 'password';
  memory_mb: number | null;
  home_free_mb: number | null;
  listening_ports: number[];
  existing_projects: string[];
  existing_install: ExistingInstallInfo | null;
  services: {
    postgres?: DetectedServiceInfo;
    redis?: DetectedServiceInfo;
  };
  local_images: LocalRelease[];
  warnings: string[];
}

export interface DetectRequest {
  target: InstallTarget;
  install_dir?: string;
}

export interface DetectResponse {
  facts: HostFacts;
  recommended_components: {
    backend: 'install' | 'none';
    worker: 'install' | 'none';
    postgres: 'install' | 'existing' | 'none';
    redis: 'install' | 'existing' | 'none';
    webui: 'reuse' | 'install';
  };
  needs_sudo_for: string[];
  recommended_image_source: 'copy' | 'target' | 'registry';
  recommended_version: string;
}

export interface CheckServiceRequest {
  target: InstallTarget;
  kind: 'postgres' | 'redis';
  host: string;
  port: number;
}

export interface CheckServiceResponse {
  reachable: boolean;
  kind: 'postgres' | 'redis';
  host: string;
  port: number;
  message: string;
}

export interface RegisterExistingRequest {
  name?: string;
  target: InstallTarget;
  install_dir?: string;
}

export interface InstallEvent {
  seq: number;
  at: number;
  kind: 'step' | 'output' | 'error' | 'done';
  message: string;
}

export interface InstallStatus {
  id: string;
  name: string;
  target: string;
  state: 'running' | 'succeeded' | 'failed';
  connection_id: string | null;
  events: InstallEvent[];
  /** Store-only installs: what other hosts enter to use them. Holds passwords. */
  store_connection?: StoreConnection | null;
}

export interface StoreConnection {
  host: string;
  install_dir: string;
  postgres?: { port: number; name: string; user: string; password: string };
  redis?: { port: number; password: string };
}

export interface ClusterStoresResponse {
  available: boolean;
  cluster_id: string | null;
  database: {
    host: string;
    port: number;
    name: string;
    username: string;
    password: string;
  } | null;
  redis: {
    host: string;
    port: number;
    db: number;
    password: string;
  } | null;
  source_backend_name: string | null;
  secret_key?: string | null;
  settings_id?: number | null;
  backend_id?: string | null;
  api_url?: string | null;
}

export const getInstallEnvironment = () => request<InstallEnvironment>('/installs/environment');

export const getClusterStores = (targetIsRemote: boolean = false, connectionId?: string) => {
  const params = new URLSearchParams();
  if (targetIsRemote) params.set('target_is_remote', 'true');
  if (connectionId) params.set('connection_id', connectionId);
  const qs = params.toString();
  return request<ClusterStoresResponse>(`/installs/cluster-stores${qs ? `?${qs}` : ''}`);
};

export const scanHostKey = (host: string, port: number) =>
  request<HostKey>('/installs/host-key', { method: 'POST', body: JSON.stringify({ host, port }) });

export const detectHost = (input: DetectRequest) =>
  request<DetectResponse>('/installs/detect', { method: 'POST', body: JSON.stringify(input) });

export const checkService = (input: CheckServiceRequest) =>
  request<CheckServiceResponse>('/installs/check-service', { method: 'POST', body: JSON.stringify(input) });

export const registerExistingInstall = (input: RegisterExistingRequest) =>
  request<Deployment>('/installs/register-existing', { method: 'POST', body: JSON.stringify(input) });

export const startInstall = (install: InstallRequest) =>
  request<{ id: string }>('/installs', { method: 'POST', body: JSON.stringify(install) });

/** Events after `after`, so a reconnecting page picks up where it left off. */
export const getInstall = (id: string, after: number) =>
  request<InstallStatus>(`/installs/${encodeURIComponent(id)}?after=${after}`);

export interface Deployment {
  id: string;
  name: string;
  target: string;
  details: {
    kind: 'local' | 'ssh';
    host?: string | null;
    port?: number;
    username?: string | null;
    install_dir: string;
    project: string;
    version: string;
    image_source: 'copy' | 'target' | 'registry';
    image_prefix?: string;
    architecture: string;
    /** The exact build running, from its image label (e.g. 0.1.0-edge.0123abcd4567). */
    image_version?: string;
    components?: InstallComponents;
  };
  connection_id: string | null;
}

export interface DeploymentOperation {
  action: 'repair' | 'upgrade' | 'uninstall' | 'services';
  /** Asked for again each time; the WebUI never stores them. */
  credentials: { password?: string; private_key?: string; sudo_password?: string };
  version?: string;
  image_source?: 'copy' | 'target' | 'registry';
  image_prefix?: string;
  delete_data?: boolean;
  remove_files?: boolean;
  /** Uninstall only: the WebUI password, checked again by the server. */
  webui_password?: string;
  /** Services only: what the host runs from now on; PostgreSQL and Redis stay as installed. */
  services?: { backend: boolean; worker: boolean; webui: boolean };
}

export const listDeployments = () => request<Deployment[]>('/deployments');

export const operateDeployment = (id: string, operation: DeploymentOperation) =>
  request<{ id: string }>(`/deployments/${encodeURIComponent(id)}/operations`, {
    method: 'POST',
    body: JSON.stringify(operation),
  });


/** This WebUI's own version, and whether a newer one can be installed. */
export interface WebUIUpdateStatus {
  version: string;
  install_kind: 'uv-tool' | 'container' | 'other';
  channel: 'release' | 'edge';
  index: string;
  latest: string | null;
  update_available: boolean;
  can_update: boolean;
  /** Why no update is offered, when none is. */
  reason: string | null;
}

export interface WebUIUpdateResult {
  version: string;
  log: string;
  restarting: boolean;
}

export const getWebUIUpdate = () => request<WebUIUpdateStatus>('/self');

/** Installs the newest version and restarts this WebUI; the reply comes before the restart. */
export const updateWebUI = () => request<WebUIUpdateResult>('/self/update', { method: 'POST' });

/** An API server in a cluster. */
export interface ClusterBackend {
  backend_id: string;
  /** The friendly name from the backend inventory, else its host. */
  name: string;
  address: string | null;
  version: string;
  status: string;
  last_seen: string;
  /** This WebUI's connection to it, when it has one. */
  connection_id: string | null;
}

export interface ClusterWorker {
  worker_id: string;
  status: string;
  current_job: string | null;
}

/** A machine running workers, whether or not it also serves the API. */
export interface ClusterWorkerHost {
  backend_id: string;
  name: string;
  status: string;
  version: string;
  active_workers: number;
  max_workers: number;
  pending_jobs: number;
  workers: ClusterWorker[];
}

export interface ClusterOverview {
  cluster_id: string;
  name: string;
  backends: ClusterBackend[];
  worker_hosts: ClusterWorkerHost[];
  answered_by: string | null;
  error: string | null;
}

export interface ClusterInvite {
  invite: string;
  name: string;
  members: { name: string; base_url: string }[];
  /** Members this WebUI cannot share, and why. */
  excluded: { name: string; reason: string }[];
  /** 2: a one-time code, redeemed over pinned HTTPS. 1: carries the members' admin tokens. */
  version: number;
  expires_at: string | null;
  warning: string | null;
}

export interface ClusterInvitePreview {
  /** Unknown for a one-time invite until it is redeemed. */
  cluster_id: string | null;
  name: string;
  members: { name: string; backend_id: string; base_url: string; already_connected: boolean }[];
  version: number;
  /** One-time invites: the member it is redeemed at, and whether it showed the expected certificate. */
  entry_url: string | null;
  fingerprint: string | null;
  verified: boolean | null;
  error: string | null;
}

export interface ClusterJoinResult {
  cluster_id: string;
  name: string;
  created: string[];
  skipped: string[];
  members?: { name: string; base_url: string | null; connection_id: string | null; note: string | null }[];
}

/** A WebUI (or other client) that joined the cluster with an invite. */
export interface ClusterClient {
  id: string;
  name: string;
  kind: string;
  created_at: string;
  last_seen_at: string | null;
  last_address: string | null;
  version: string | null;
  revoked_at: string | null;
  /** This WebUI. */
  is_self: boolean;
}

const clusterPath = (clusterId: string) => `/clusters/${encodeURIComponent(clusterId)}`;

export const getClusterOverview = (clusterId: string) => request<ClusterOverview>(`${clusterPath(clusterId)}/overview`);

export const renameCluster = (clusterId: string, name: string) =>
  request<{ name: string }>(`${clusterPath(clusterId)}/name`, { method: 'PUT', body: JSON.stringify({ name }) });

/** One invite for the whole cluster: a one-time code, or (without HTTPS members) the members' admin tokens. */
export const getClusterInvite = (clusterId: string) => request<ClusterInvite>(`${clusterPath(clusterId)}/invite`);

export const previewClusterInvite = (invite: string) =>
  request<ClusterInvitePreview>('/clusters/preview-invite', { method: 'POST', body: JSON.stringify({ ticket: invite }) });

export const joinCluster = (invite: string) =>
  request<ClusterJoinResult>('/clusters/join', { method: 'POST', body: JSON.stringify({ ticket: invite }) });

/** The deployments this WebUI manages in the cluster, API servers first. */
export const listClusterDeployments = (clusterId: string) => request<Deployment[]>(`${clusterPath(clusterId)}/deployments`);

export interface ClusterUpgrade {
  version: string;
  image_source?: Deployment['details']['image_source'];
  image_prefix?: string;
  /** SSH credentials per deployment id; never stored. */
  credentials: Record<string, { password?: string; private_key?: string; sudo_password?: string }>;
  deployment_ids?: string[];
}

/** Upgrades the cluster's deployments one after another, in one run. */
export const upgradeCluster = (clusterId: string, upgrade: ClusterUpgrade) =>
  request<{ id: string }>(`${clusterPath(clusterId)}/upgrade`, { method: 'POST', body: JSON.stringify(upgrade) });

export type NodeRole = 'backend' | 'workers' | 'webui' | 'postgres' | 'redis';
export type NodeState = 'healthy' | 'warning' | 'offline' | 'unknown';

/** One service on a host. */
export interface ClusterNode {
  role: NodeRole;
  name: string;
  state: NodeState;
  version: string | null;
  detail: string | null;
  last_seen: string | null;
  backend_id: string | null;
  client_id: string | null;
  connection_id: string | null;
  is_self: boolean;
  /** Put there by this WebUI's installer, but not reporting. */
  installed_only: boolean;
}

/** A machine in the cluster and the nodes it runs. */
export interface ClusterHost {
  key: string;
  name: string;
  address: string | null;
  roles: NodeRole[];
  state: NodeState;
  nodes: ClusterNode[];
  deployment_id: string | null;
}

export interface ClusterHosts {
  cluster_id: string;
  name: string;
  hosts: ClusterHost[];
  answered_by: string | null;
  error: string | null;
}

export const getClusterHosts = (clusterId: string) => request<ClusterHosts>(`${clusterPath(clusterId)}/hosts`);

/** Names a host (by its key); an empty name goes back to the one it is found by. */
export const renameHost = (key: string, name: string) =>
  request<{ key: string; name: string }>('/hosts/name', { method: 'PUT', body: JSON.stringify({ key, name }) });

/** The cluster this WebUI opens on, for everyone signing in; null for none. */
export const setMainCluster = (clusterId: string | null) =>
  request<{ cluster_id: string | null }>('/clusters/main', {
    method: 'PUT',
    body: JSON.stringify({ cluster_id: clusterId }),
  });

export const listClusterClients = (clusterId: string) => request<ClusterClient[]>(`${clusterPath(clusterId)}/clients`);

export const revokeClusterClient = (clusterId: string, clientId: string) =>
  request<void>(`${clusterPath(clusterId)}/clients/${encodeURIComponent(clientId)}`, { method: 'DELETE' });

export const isClusterInvite = (value: string) => value.trim().startsWith('usr://cluster/');
