import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { AppProviders } from '../../app/AppProviders';
import { completeSetup, getSetupStatus } from '../../api/setup';
import type {
  DRMConfig,
  DatabaseConnectionRequest,
  NetworkConfig,
  RedisConnectionRequest,
  SetupAuthRequest,
  SetupStatusResponse,
  StagingDirectory,
} from '../../api/types/setup';
import {
  checkService,
  connectionHome,
  detectHost,
  getClusterStores,
  getInstallEnvironment,
  listClusters,
  listConnections,
  listDeployments,
  operateDeployment,
  registerExistingInstall,
  scanHostKey,
  startInstall,
  type BackendConnection,
  type CheckServiceResponse,
  type ClusterStoresResponse,
  type ComponentSelection,
  type Deployment,
  type DetectResponse,
  type HostKey,
  type InstallEnvironment,
  type InstallTarget,
  type StoreConnection,
  type StoreMode,
  type WebUIMode,
  type ClusterJoinResult,
} from '../../api/webui';
import { RunLog } from '../connections/RunLog';
import { followInApp } from '../connections/lib/navigation';
import { useInstallRun } from '../connections/lib/useInstallRun';
import { JoinClusterForm } from '../connections/JoinClusterForm';
import { joinSummary } from '../connections/lib/joinSummary';
import { DatabaseConnectionFields } from '../setup/components/DatabaseConnectionFields';
import { RedisConnectionFields } from '../setup/components/RedisConnectionFields';
import { SetupAuthsStep } from '../setup/components/SetupAuthsStep';
import { SetupDrmStep } from '../setup/components/SetupDrmStep';
import { SetupHint } from '../setup/components/SetupHint';
import { SetupReviewStep } from '../setup/components/SetupReviewStep';
import { SetupStepIndicator } from '../setup/components/SetupStepIndicator';
import { SetupStorageNetworkStep } from '../setup/components/SetupStorageNetworkStep';
import {
  COMPUTE_CHOICES,
  COMPUTE_LABELS,
  DEFAULT_COMPONENTS,
  applyComponentChange,
  applyComputeChoice,
  computeChoice,
  getCardRules,
  validateComponents,
} from './lib/componentRules';
import { DEFAULT_IMAGE_REGISTRY, type ImageSource, normalizeImagePrefix, versionForSource } from './lib/imageVersion';
import { nameNewCluster } from './lib/nameNewCluster';
import { ArchitectureDiagram } from './ArchitectureDiagram';
import type { PlannedInstall } from './lib/architecturePlan';
import './SetupWizard.css';

const WIZARD_STEPS = [
  'Host',
  'Components',
  'Connections',
  'Review & Install',
  'Configure Backend',
  'Done',
] as const;

const MODE_LABELS: Record<StoreMode, string> = {
  install: 'Install here',
  existing: 'Use existing',
  none: 'Not here',
};

/** The host's own copy of a key of this type, for comparing fingerprints. */
function hostKeyFile(algorithm: string): string {
  const type = algorithm.startsWith('ssh-ed25519')
    ? 'ed25519'
    : algorithm.startsWith('ecdsa')
      ? 'ecdsa'
      : 'rsa';
  return `/etc/ssh/ssh_host_${type}_key.pub`;
}

function nextFreePort(listening: number[], start: number): number {
  const used = new Set(listening);
  for (let p = start; p < start + 100; p += 1) {
    if (!used.has(p)) return p;
  }
  return start;
}

/**
 * Step 5: Inline backend configuration mounted inside `<AppProviders connectionId={...}>`
 * (`BackendScope`) so `/api/v1/setup/*`, `/api/v1/filesystem`, and `/api/v1/network/*`
 * all talk to `/b/{connectionId}/api/v1/*`.
 */
function InlineBackendConfigurator({
  onFinished,
}: {
  onFinished: (authWarnings: string[]) => void;
}) {
  const queryClient = useQueryClient();
  const [subStep, setSubStep] = useState<'storage' | 'drm' | 'auths' | 'review'>('storage');
  const [error, setError] = useState<string | null>(null);

  const [downloadDirs, setDownloadDirs] = useState<string[]>(['']);
  const [networkConfig, setNetworkConfig] = useState<NetworkConfig>({
    max_connections: -1,
    proxies: [],
    proxy_fallback: false,
  });
  const [drmConfig, setDrmConfig] = useState<DRMConfig>({
    device_client_blob_filepath: null,
    device_private_key_filepath: null,
  });
  const [stagingDirectory, setStagingDirectory] = useState<StagingDirectory | null>(null);
  const [auths, setAuths] = useState<SetupAuthRequest[]>([]);
  const [hostname, setHostname] = useState('');

  const { data: setupStatus } = useQuery<SetupStatusResponse>({
    queryKey: ['setup-status'],
    queryFn: () => getSetupStatus(),
  });

  const completeMutation = useMutation({
    mutationFn: () => {
      const activeDirs = downloadDirs.filter((dir) => dir.trim());
      const activeAuths = auths.filter((auth) => auth.curl_command.trim());
      const activeStagingDirectories =
        stagingDirectory && stagingDirectory.path.trim()
          ? [
              {
                ...stagingDirectory,
                path: stagingDirectory.path.trim(),
              },
            ]
          : [];
      return completeSetup({
        database: null,
        redis: null,
        drm: drmConfig,
        network: networkConfig,
        auths: activeAuths,
        download_directories: activeDirs,
        staging_directories: activeStagingDirectories,
        hostname: setupStatus?.backend_id ? null : hostname || null,
      });
    },
    onSuccess: async (result) => {
      queryClient.invalidateQueries({ queryKey: ['settings'] });
      queryClient.invalidateQueries({ queryKey: ['setup-status'] });
      // The cached bootstrap still says "not configured"; refresh it first, or
      // the backend's setup guard sends the next page back to /setup for a moment.
      await queryClient.refetchQueries({ queryKey: ['system-bootstrap'] });
      onFinished(result.auth_errors ?? []);
    },
    onError: (err: Error) => setError(err.message || 'Backend configuration failed'),
  });

  return (
    <>
      {error && (
        <div className="setup-error" style={{ margin: 'var(--space-5) var(--space-6) 0' }}>
          <span>{error}</span>
          <button className="setup-error-dismiss" onClick={() => setError(null)}>
            ✕
          </button>
        </div>
      )}

      {subStep === 'storage' && (
        <SetupStorageNetworkStep
          downloadDirs={downloadDirs}
          setDownloadDirs={setDownloadDirs}
          stagingDirectory={stagingDirectory}
          setStagingDirectory={setStagingDirectory}
          networkConfig={networkConfig}
          setNetworkConfig={setNetworkConfig}
          dataDirectory={setupStatus?.data_directory ?? ''}
          onNext={() => setSubStep('drm')}
        />
      )}

      {subStep === 'drm' && (
        <SetupDrmStep
          drmConfig={drmConfig}
          setDrmConfig={setDrmConfig}
          onBack={() => setSubStep('storage')}
          onNext={() => setSubStep('auths')}
        />
      )}

      {subStep === 'auths' && (
        <SetupAuthsStep
          auths={auths}
          setAuths={setAuths}
          availableProxies={networkConfig.proxies.map((proxy) => proxy.url)}
          onBack={() => setSubStep('drm')}
          onNext={() => setSubStep('review')}
        />
      )}

      {subStep === 'review' && (
        <SetupReviewStep
          dbConfig={{
            host: 'localhost',
            port: 5432,
            name: 'ultima_archive',
            username: 'ultimascraper',
            password: '',
          }}
          skipDb={true}
          redisConfig={{
            host: 'localhost',
            port: 6379,
            db: 0,
            password: '',
            enabled: true,
          }}
          configuredRedis={setupStatus?.redis_target ?? 'configured'}
          downloadDirs={downloadDirs}
          proxies={networkConfig.proxies}
          stagingDirectory={stagingDirectory}
          auths={auths}
          hostname={hostname}
          setHostname={setHostname}
          pinnedBackendId={setupStatus?.backend_id ?? null}
          onBack={() => setSubStep('auths')}
          onComplete={() => completeMutation.mutate()}
          isCompleting={completeMutation.isPending}
        />
      )}
    </>
  );
}

/** Where backends and workers on other hosts find a store-only install. */
function StoreConnectionDetails({ connection }: { connection: StoreConnection }) {
  return (
    <div className="setup-summary" style={{ marginBottom: 'var(--space-4)' }} data-testid="store-connection">
      <p className="setup-form-hint" style={{ marginTop: 0 }}>
        Enter these on the hosts that use these services. They are shown once; the host keeps them
        in <code>{connection.install_dir}/.env</code>.
      </p>
      {connection.postgres && (
        <div className="setup-summary-row">
          <span className="setup-summary-label">PostgreSQL</span>
          <span className="setup-summary-value mono">
            {connection.postgres.user}@{connection.host}:{connection.postgres.port}/
            {connection.postgres.name} · password {connection.postgres.password}
          </span>
        </div>
      )}
      {connection.redis && (
        <div className="setup-summary-row">
          <span className="setup-summary-label">Redis</span>
          <span className="setup-summary-value mono">
            {connection.host}:{connection.redis.port} · password {connection.redis.password}
          </span>
        </div>
      )}
    </div>
  );
}

/** The cluster a host is being added to, from the cluster page's Add host. */
export interface SetupWizardCluster {
  clusterId: string;
  /** A connection to one of its backends: where its PostgreSQL and Redis come from. */
  connectionId: string;
  name: string;
}

const CLUSTER_STEPS = ['Host', 'Components', 'Review & Install', 'Configure Backend', 'Done'] as const;

/** A host joining a cluster runs its compute against the cluster's own stores. */
function withClusterStores(selection: ComponentSelection): ComponentSelection {
  const computes = selection.backend === 'install' || selection.worker === 'install';
  const store: StoreMode = computes ? 'existing' : 'none';
  return { ...selection, postgres: store, redis: store };
}

/**
 * Unified setup wizard: one flow from "nothing installed" to "backend configured".
 *
 * As `/setup` it is the first run, creating the first cluster. With `cluster`
 * (in the cluster page's Add host, `layout="modal"`) it adds a host to that
 * cluster: PostgreSQL and Redis are the cluster's, unless Advanced says
 * otherwise, and a worker-only host works for it without asking.
 */
export function SetupWizardPage({
  cluster: clusterProp,
  layout = 'page',
  onDone,
}: {
  cluster?: SetupWizardCluster;
  layout?: 'page' | 'modal';
  onDone?: (connectionId: string | null) => void;
} = {}) {
  // Without a cluster given (first run, /setup), step 0 asks: create a cluster or join one.
  const [step, setStep] = useState(clusterProp ? 1 : 0);
  const [clusterChoice, setClusterChoice] = useState<'create' | 'join' | null>(null);
  // The cluster joined with an invite at step 0; the rest then adds a host to it.
  const [joinedCluster, setJoinedCluster] = useState<SetupWizardCluster | null>(null);
  const [joinMessage, setJoinMessage] = useState('');
  const cluster = clusterProp ?? joinedCluster ?? undefined;
  // Adding to a cluster, "existing" PostgreSQL and Redis are the cluster's own:
  // known, so not asked for, and checked from the host on Review.
  const lockStores = Boolean(cluster);
  // A new database is a new cluster: its name, set once the backend reports it.
  const [clusterName, setClusterName] = useState('Home');
  const [error, setError] = useState('');

  // Environment & target state
  const [environment, setEnvironment] = useState<InstallEnvironment | null>(null);
  const [where, setWhere] = useState<'local' | 'ssh'>('local');
  // Install where: chosen with the Local and Remote tiles; nothing until then.
  const [hostChoice, setHostChoice] = useState<'local' | 'remote' | null>(null);
  // Local goes on to Components as soon as this machine is detected.
  const [advanceWhenDetected, setAdvanceWhenDetected] = useState(false);
  const whereRef = useRef<'local' | 'ssh'>('local');
  const userSelectedWhereRef = useRef(false);
  const detectionRequestIdRef = useRef(0);

  useEffect(() => {
    whereRef.current = where;
  }, [where]);
  const [thisMachineOverSsh, setThisMachineOverSsh] = useState(false);
  const [host, setHost] = useState('');
  const [port, setPort] = useState(22);
  const [username, setUsername] = useState('');
  const [authMethod, setAuthMethod] = useState<'password' | 'key'>('password');
  const [password, setPassword] = useState('');
  const [privateKey, setPrivateKey] = useState('');
  const [sudoPassword, setSudoPassword] = useState('');
  const [hostKey, setHostKey] = useState<HostKey | null>(null);
  const [hostKeyAccepted, setHostKeyAccepted] = useState(false);
  const [checkingHost, setCheckingHost] = useState(false);

  // Detection state
  const [detecting, setDetecting] = useState(false);
  const [detection, setDetection] = useState<DetectResponse | null>(null);
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [registeringExisting, setRegisteringExisting] = useState(false);

  // Component selection state
  const [components, setComponents] = useState<ComponentSelection>(() =>
    cluster ? withClusterStores({ ...DEFAULT_COMPONENTS, backend: 'none' }) : DEFAULT_COMPONENTS,
  );
  const [confirmExtraWebui, setConfirmExtraWebui] = useState(false);
  const [connections, setConnections] = useState<BackendConnection[]>([]);
  const [joinConnectionId, setJoinConnectionId] = useState(cluster?.connectionId ?? '');
  const [postgresPort, setPostgresPort] = useState(5432);
  const [redisPort, setRedisPort] = useState(6379);

  // Existing service connection state (Step 3)
  const [dbConfig, setDbConfig] = useState<DatabaseConnectionRequest>({
    host: 'localhost',
    port: 5432,
    name: 'ultima_archive',
    username: 'ultimascraper',
    password: '',
  });
  const [redisConfig, setRedisConfig] = useState<RedisConnectionRequest>({
    host: 'localhost',
    port: 6379,
    db: 0,
    password: '',
    enabled: true,
  });
  const [pgCheck, setPgCheck] = useState<CheckServiceResponse | null>(null);
  const [checkingPg, setCheckingPg] = useState(false);
  const [redisCheck, setRedisCheck] = useState<CheckServiceResponse | null>(null);
  const [checkingRedis, setCheckingRedis] = useState(false);

  // Review & install state (Step 4)
  const [name, setName] = useState('');
  const [nameEdited, setNameEdited] = useState(false);
  const [installDir, setInstallDir] = useState('~/ultimascraper');
  const [imageSource, setImageSource] = useState<'copy' | 'target' | 'registry'>('registry');
  const [version, setVersion] = useState('');
  // Until edited, the version follows the image source (see versionForSource).
  const [versionEdited, setVersionEdited] = useState(false);
  const [imagePrefix, setImagePrefix] = useState(DEFAULT_IMAGE_REGISTRY);
  const [installDocker, setInstallDocker] = useState(false);
  const [shareBackend, setShareBackend] = useState(false);
  const [startingInstall, setStartingInstall] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  // A repair of an existing install skips the first-time backend configuration.
  const [runKind, setRunKind] = useState<'install' | 'repair'>('install');
  const { status: installStatus, events: installEvents } = useInstallRun(runId);

  // Post-install state (Step 5 & 6)
  const [installedConnectionId, setInstalledConnectionId] = useState<string | null>(null);
  const [authWarnings, setAuthWarnings] = useState<string[]>([]);

  // Cluster inheritance: query existing database and redis details
  const isTargetRemote = where === 'ssh';
  const [clusterStores, setClusterStores] = useState<ClusterStoresResponse | null>(null);
  useEffect(() => {
    let cancelled = false;
    getClusterStores(isTargetRemote, joinConnectionId || undefined)
      .then((res) => {
        if (!cancelled) setClusterStores(res);
      })
      .catch(() => {
        if (!cancelled) setClusterStores(null);
      });
    return () => {
      cancelled = true;
    };
  }, [isTargetRemote, joinConnectionId]);

  const applyClusterStoreDefaults = useCallback(
    (force = false) => {
      if (!clusterStores?.available) return;
      if (clusterStores.database) {
        setDbConfig((prev) => {
          if (force || (prev.host === 'localhost' && prev.password === '')) {
            return {
              host: clusterStores.database!.host,
              port: clusterStores.database!.port,
              name: clusterStores.database!.name,
              username: clusterStores.database!.username,
              password: clusterStores.database!.password,
            };
          }
          return prev;
        });
      }
      if (clusterStores.redis) {
        setRedisConfig((prev) => {
          if (force || (prev.host === 'localhost' && prev.password === '')) {
            return {
              host: clusterStores.redis!.host,
              port: clusterStores.redis!.port,
              db: clusterStores.redis!.db,
              password: clusterStores.redis!.password,
              enabled: true,
            };
          }
          return prev;
        });
      }
    },
    [clusterStores],
  );

  useEffect(() => {
    if (clusterStores?.available) {
      applyClusterStoreDefaults(false);
    }
  }, [clusterStores, applyClusterStoreDefaults]);

  const buildTarget = useCallback((): InstallTarget => {
    if (where === 'local') {
      return {
        kind: 'local',
        sudo_password: sudoPassword || undefined,
      };
    }
    return {
      kind: 'ssh',
      host: host.trim(),
      port,
      username: username.trim(),
      password: authMethod === 'password' ? password : undefined,
      private_key: authMethod === 'key' ? privateKey : undefined,
      host_key: hostKey?.key,
      sudo_password: sudoPassword || undefined,
    };
  }, [authMethod, host, hostKey?.key, password, port, privateKey, sudoPassword, username, where]);

  const applyDetection = useCallback(
    (result: DetectResponse) => {
      setDetection(result);
      // Adding to a cluster keeps its own choice of components.
      if (!cluster) setComponents(result.recommended_components);
      setImageSource(result.recommended_image_source);
      if (result.recommended_version) {
        setVersion(result.recommended_version);
      }
      if (!nameEdited) {
        setName(result.facts.hostname || host.trim() || 'local');
      }
      if (!result.facts.docker_version || !result.facts.compose_version) {
        setInstallDocker(true);
      }
      setPostgresPort(nextFreePort(result.facts.listening_ports ?? [], 5432));
      setRedisPort(nextFreePort(result.facts.listening_ports ?? [], 6379));
      const detectedPg = result.facts.services?.postgres;
      if (detectedPg?.detected && !cluster) {
        setDbConfig((prev) => ({ ...prev, host: 'localhost', port: detectedPg.port || 5432 }));
      } else if (clusterStores?.available && clusterStores.database) {
        setDbConfig({
          host: clusterStores.database.host,
          port: clusterStores.database.port,
          name: clusterStores.database.name,
          username: clusterStores.database.username,
          password: clusterStores.database.password,
        });
      }
      const detectedRedis = result.facts.services?.redis;
      if (detectedRedis?.detected && !cluster) {
        setRedisConfig((prev) => ({ ...prev, host: 'localhost', port: detectedRedis.port || 6379 }));
      } else if (clusterStores?.available && clusterStores.redis) {
        setRedisConfig({
          host: clusterStores.redis.host,
          port: clusterStores.redis.port,
          db: clusterStores.redis.db,
          password: clusterStores.redis.password,
          enabled: true,
        });
      }
    },
    [cluster, clusterStores, host, nameEdited],
  );

  const runDetection = useCallback(
    async (targetOverride?: InstallTarget) => {
      const requestId = ++detectionRequestIdRef.current;
      const target = targetOverride ?? buildTarget();
      setError('');
      setDetecting(true);
      try {
        const result = await detectHost({
          target,
          install_dir: installDir.trim() || '~/ultimascraper',
        });
        if (requestId !== detectionRequestIdRef.current) return;
        if (whereRef.current !== target.kind) return;
        applyDetection(result);
      } catch (detectErr) {
        if (requestId !== detectionRequestIdRef.current) return;
        if (whereRef.current !== target.kind) return;
        setError(detectErr instanceof Error ? detectErr.message : 'Could not inspect the host.');
      } finally {
        if (requestId === detectionRequestIdRef.current && whereRef.current === target.kind) {
          setDetecting(false);
        }
      }
    },
    [applyDetection, buildTarget, installDir],
  );

  // Initial load: load environment, connections, deployments, and auto-detect "This machine".
  useEffect(() => {
    let active = true;
    listConnections()
      .then((loaded) => {
        if (!active) return;
        setConnections(loaded);
        if (loaded[0] && !cluster) setJoinConnectionId(loaded[0].id);
      })
      .catch(() => undefined);
    listDeployments()
      .then((loaded) => {
        if (active) setDeployments(loaded);
      })
      .catch(() => undefined);

    getInstallEnvironment()
      .then((loaded) => {
        if (!active) return;
        setEnvironment(loaded);
        if (loaded.version) setVersion((prev) => prev || loaded.version);
        if (userSelectedWhereRef.current) return;
        if (!loaded.local_available && loaded.in_container) {
          setWhere('ssh');
          whereRef.current = 'ssh';
          setThisMachineOverSsh(true);
          setHost('host.docker.internal');
          return;
        }
        setWhere('local');
        whereRef.current = 'local';
        void runDetection({ kind: 'local' });
      })
      .catch(() => {
        if (!active || userSelectedWhereRef.current) return;
        void runDetection({ kind: 'local' });
      });

    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // In SSH mode, run detection automatically after the host key is accepted.
  useEffect(() => {
    if (
      where === 'ssh' &&
      hostKey &&
      hostKeyAccepted &&
      username.trim() &&
      (authMethod === 'password' ? password : privateKey.trim())
    ) {
      void runDetection();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hostKeyAccepted]);

  // A backend with its own new PostgreSQL starts a new cluster, which gets the name given.
  const createsCluster = !cluster && components.backend === 'install' && components.postgres === 'install';

  // Transition automatically when the install run finishes.
  useEffect(() => {
    if (!installStatus || installStatus.state !== 'succeeded') return;
    if (installStatus.connection_id) {
      setInstalledConnectionId(installStatus.connection_id);
      if (runKind === 'install' && createsCluster) {
        void nameNewCluster(installStatus.connection_id, clusterName);
      }
    }
    if (runKind === 'install' && components.backend === 'install' && installStatus.connection_id) {
      setStep(5);
    } else {
      setStep(6);
    }
    // Once per finished run: the name and choices are those it was started with.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [components.backend, installStatus, runKind]);

  const checkHost = async () => {
    setError('');
    setHostKey(null);
    setHostKeyAccepted(false);
    setDetection(null);
    setCheckingHost(true);
    const targetHost = host.trim();
    const targetPort = port;
    try {
      const key = await scanHostKey(targetHost, targetPort);
      if (whereRef.current === 'ssh' && host.trim() === targetHost) {
        setHostKey(key);
      }
    } catch (scanError) {
      if (whereRef.current === 'ssh' && host.trim() === targetHost) {
        setError(scanError instanceof Error ? scanError.message : 'Could not reach the host.');
      }
    } finally {
      if (whereRef.current === 'ssh' && host.trim() === targetHost) {
        setCheckingHost(false);
      }
    }
  };

  // Remote: the host key is fetched as soon as there is an address to fetch it from.
  useEffect(() => {
    if (step !== 1 || where !== 'ssh' || !host.trim()) return;
    const timer = window.setTimeout(() => void checkHost(), 600);
    return () => window.clearTimeout(timer);
    // checkHost reads the host and port this effect runs for.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [host, port, where, step]);

  // Local: on to Components once this machine is detected, unless there is
  // something to see first: an install to connect or repair, warnings, missing
  // Docker, or services found on it.
  useEffect(() => {
    if (!advanceWhenDetected || detecting || !detection || where !== 'local') return;
    setAdvanceWhenDetected(false);
    const found = detection.facts;
    const services = Object.values(found.services ?? {});
    const worthSeeing =
      Boolean(found.existing_install) ||
      found.existing_projects.length > 0 ||
      found.warnings.length > 0 ||
      !found.docker_version ||
      !found.compose_version ||
      services.some((service) => service?.detected || (service?.unreachable_containers?.length ?? 0) > 0);
    if (!worthSeeing) setStep(2);
  }, [advanceWhenDetected, detecting, detection, where]);

  const chooseLocal = () => {
    setHostChoice('local');
    setError('');
    userSelectedWhereRef.current = true;
    if (environment && !environment.local_available && environment.in_container) {
      // This WebUI's container reaches the machine it runs on over SSH.
      whereRef.current = 'ssh';
      setWhere('ssh');
      setThisMachineOverSsh(true);
      setHost('host.docker.internal');
      setDetection(null);
      return;
    }
    const detectedHere = whereRef.current === 'local' && (detection !== null || detecting);
    whereRef.current = 'local';
    setWhere('local');
    setThisMachineOverSsh(false);
    setAdvanceWhenDetected(true);
    if (!detectedHere) {
      setDetection(null);
      void runDetection({ kind: 'local' });
    }
  };

  const chooseRemote = () => {
    setHostChoice('remote');
    setError('');
    userSelectedWhereRef.current = true;
    whereRef.current = 'ssh';
    detectionRequestIdRef.current += 1;
    setWhere('ssh');
    setThisMachineOverSsh(false);
    setAdvanceWhenDetected(false);
    setHost('');
    setHostKey(null);
    setHostKeyAccepted(false);
    setDetection(null);
    setDetecting(false);
  };

  const handleJoined = async (result: ClusterJoinResult) => {
    setJoinMessage(joinSummary(result));
    // A connection to one of its backends: where its PostgreSQL and Redis come from.
    let connectionId: string | null =
      result.members?.find((member) => member.connection_id)?.connection_id ?? result.created[0] ?? null;
    if (!connectionId) {
      try {
        const known = await listClusters();
        connectionId = known.clusters.find((item) => item.cluster_id === result.cluster_id)?.connection_ids[0] ?? null;
      } catch {
        connectionId = null;
      }
    }
    if (!connectionId) return;
    setJoinedCluster({ clusterId: result.cluster_id, connectionId, name: result.name });
    setJoinConnectionId(connectionId);
    setComponents(withClusterStores({ ...DEFAULT_COMPONENTS, backend: 'none' }));
    listConnections().then(setConnections, () => undefined);
  };

  const handleRegisterExisting = async () => {
    setError('');
    setRegisteringExisting(true);
    try {
      const regName =
        name.trim() ||
        detection?.facts.existing_install?.project ||
        detection?.facts.hostname ||
        'local';
      const registered = await registerExistingInstall({
        name: regName,
        target: buildTarget(),
        install_dir: installDir.trim() || '~/ultimascraper',
      });
      setName(regName);
      setInstalledConnectionId(registered.connection_id);
      setStep(6);
    } catch (regError) {
      setError(
        regError instanceof Error ? regError.message : 'Could not register the existing install.',
      );
    } finally {
      setRegisteringExisting(false);
    }
  };

  const handleRepairExisting = async (deployment: Deployment) => {
    setError('');
    try {
      const started = await operateDeployment(deployment.id, {
        action: 'repair',
        credentials: {
          password: where === 'ssh' && authMethod === 'password' ? password : undefined,
          private_key: where === 'ssh' && authMethod === 'key' ? privateKey : undefined,
          sudo_password: sudoPassword || undefined,
        },
      });
      setRunKind('repair');
      setRunId(started.id);
      setStep(4);
    } catch (opError) {
      setError(opError instanceof Error ? opError.message : 'Could not start repair.');
    }
  };

  const handleCheckPostgres = async () => {
    setCheckingPg(true);
    setPgCheck(null);
    try {
      const res = await checkService({
        target: buildTarget(),
        kind: 'postgres',
        host: dbConfig.host.trim(),
        port: dbConfig.port,
      });
      setPgCheck(res);
    } catch (err) {
      setPgCheck({
        reachable: false,
        kind: 'postgres',
        host: dbConfig.host.trim(),
        port: dbConfig.port,
        message: err instanceof Error ? err.message : 'Check failed',
      });
    } finally {
      setCheckingPg(false);
    }
  };

  const handleCheckRedis = async () => {
    setCheckingRedis(true);
    setRedisCheck(null);
    try {
      const res = await checkService({
        target: buildTarget(),
        kind: 'redis',
        host: redisConfig.host.trim(),
        port: redisConfig.port,
      });
      setRedisCheck(res);
    } catch (err) {
      setRedisCheck({
        reachable: false,
        kind: 'redis',
        host: redisConfig.host.trim(),
        port: redisConfig.port,
        message: err instanceof Error ? err.message : 'Check failed',
      });
    } finally {
      setCheckingRedis(false);
    }
  };

  // Adding to a cluster: check this host reaches the cluster's stores before installing.
  useEffect(() => {
    if (step !== 4 || !lockStores) return;
    if (components.postgres === 'existing' && !pgCheck && !checkingPg) void handleCheckPostgres();
    if (components.redis === 'existing' && !redisCheck && !checkingRedis) void handleCheckRedis();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, lockStores]);

  const handleStartInstall = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    setStartingInstall(true);
    try {
      const storeOnly = components.backend === 'none' && components.worker === 'none';
      const started = await startInstall({
        name: (name.trim() || detection?.facts.hostname || host.trim() || 'local').slice(0, 60),
        target: buildTarget(),
        components,
        install_dir: installDir.trim() || '~/ultimascraper',
        image_source: imageSource,
        version: version.trim() || versionForSource(imageSource, detection, environment),
        image_prefix: imageSource === 'registry' ? normalizeImagePrefix(imagePrefix) : undefined,
        install_docker: installDocker,
        share_backend: components.backend === 'install' ? shareBackend : undefined,
        database:
          components.postgres === 'existing'
            ? {
                host: dbConfig.host.trim(),
                port: dbConfig.port,
                name: dbConfig.name.trim(),
                user: dbConfig.username.trim(),
                password: dbConfig.password,
              }
            : undefined,
        redis_host: components.redis === 'existing' ? redisConfig.host.trim() : undefined,
        redis_password:
          components.redis === 'existing' ? redisConfig.password || undefined : undefined,
        join_connection_id:
          components.worker === 'install' && components.backend === 'none'
            ? joinConnectionId || undefined
            : undefined,
        postgres_port:
          storeOnly && components.postgres === 'install' ? postgresPort : undefined,
        // An existing Redis's port, or the port a store-only host publishes.
        redis_port:
          components.redis === 'existing'
            ? redisConfig.port
            : storeOnly && components.redis === 'install'
              ? redisPort
              : undefined,
      });
      setRunKind('install');
      setRunId(started.id);
    } catch (startErr) {
      setError(startErr instanceof Error ? startErr.message : 'The install did not start.');
    } finally {
      setStartingInstall(false);
    }
  };

  const storeConnection = runKind === 'install' ? installStatus?.store_connection ?? null : null;
  const facts = detection?.facts ?? null;
  const targetHostname =
    facts?.hostname || (where === 'ssh' ? host.trim() : '') || (where === 'local' ? 'this machine' : 'this host');
  const needsSudoFor = detection?.needs_sudo_for ?? [];
  const showSudoPasswordField = needsSudoFor.length > 0 && facts?.sudo_mode === 'password';

  const cardRules = getCardRules(components);
  const componentValidation = validateComponents(components);
  // Adding to a cluster, its stores are known: they are checked on Review instead.
  const needsConnectionsStep =
    !lockStores && (components.postgres === 'existing' || components.redis === 'existing');
  const isLocalTarget = where === 'local' || thisMachineOverSsh;
  const localPgDetected = Boolean(facts?.services?.postgres?.detected);
  const localRedisDetected = Boolean(facts?.services?.redis?.detected);
  const storeOnlyHost = components.backend === 'none' && components.worker === 'none';

  const detectedServicesList = [
    ...(facts?.services?.postgres?.detected
      ? [`postgres (:${facts.services.postgres.port || 5432})`]
      : []),
    ...(facts?.services?.redis?.detected
      ? [`redis (:${facts.services.redis.port || 6379})`]
      : []),
  ];

  const unreachableStores = [
    ...(facts?.services?.postgres?.unreachable_containers ?? []),
    ...(facts?.services?.redis?.unreachable_containers ?? []),
  ];

  const existingPassedChecks =
    (components.postgres !== 'existing' || Boolean(pgCheck?.reachable)) &&
    (components.redis !== 'existing' || Boolean(redisCheck?.reachable));

  const canLeaveComponents =
    componentValidation.valid &&
    (components.worker !== 'install' ||
      components.backend === 'install' ||
      Boolean(joinConnectionId)) &&
    (!isLocalTarget || components.webui !== 'install' || confirmExtraWebui);

  const matchingDeployment = deployments.find(
    (dep) =>
      dep.details.install_dir === (facts?.existing_install ? installDir : '') ||
      (facts?.existing_install?.project && dep.details.project === facts.existing_install.project),
  );

  const computes = components.backend === 'install' || components.worker === 'install';
  const clientOnly =
    Boolean(cluster) &&
    components.backend === 'none' &&
    components.worker === 'none' &&
    components.webui === 'reuse';
  // What Review draws: this install within every cluster this WebUI manages.
  const plannedInstall: PlannedInstall = {
    hostName: name.trim() || facts?.hostname || host.trim() || 'This machine',
    location: where === 'local' || thisMachineOverSsh ? 'Local' : 'Remote',
    address: where === 'ssh' && !thisMachineOverSsh ? host.trim() || null : null,
    installs: {
      backend: components.backend === 'install',
      workers: components.worker === 'install',
      webui: components.webui === 'install',
      postgres: components.postgres === 'install',
      redis: components.redis === 'install',
    },
    postgres: components.postgres === 'existing' ? `${dbConfig.host}:${dbConfig.port}` : null,
    redis: components.redis === 'existing' ? `${redisConfig.host}:${redisConfig.port}` : null,
    target: cluster
      ? { kind: 'existing', clusterId: cluster.clusterId, connectionId: cluster.connectionId }
      : !computes
        ? { kind: 'none' }
        : createsCluster
          ? { kind: 'new', name: clusterName.trim() }
          : components.backend === 'none'
            ? { kind: 'existing', clusterId: null, connectionId: joinConnectionId || null }
            : { kind: 'existing', clusterId: clusterStores?.cluster_id ?? null, connectionId: null },
  };

  const extraWebuiPort = nextFreePort(facts?.listening_ports ?? [], 21120);

  return (
    <div className={`setup-page${layout === 'modal' ? ' is-embedded' : ''}`}>
      {layout === 'page' && (
      <>
      <div className="setup-header">
        <img className="setup-logo" src="/favicon.svg" alt="UltimaScraper" />
        <h1>Set up UltimaScraper</h1>
        <p>Install and configure your environment in one flow</p>
      </div>
      </>
      )}

      <SetupStepIndicator
        current={(cluster && step >= 3 ? step - 1 : step) + (clusterProp ? 0 : 1)}
        labels={
          clusterProp
            ? CLUSTER_STEPS
            : joinedCluster
              ? (['Cluster', ...CLUSTER_STEPS] as const)
              : (['Cluster', ...WIZARD_STEPS] as const)
        }
      />

      <div className="setup-card setup-wizard-card">
        {error && (
          <div
            className="setup-error"
            role="alert"
            style={{ margin: 'var(--space-5) var(--space-6) 0' }}
          >
            <span>{error}</span>
            <button className="setup-error-dismiss" onClick={() => setError('')}>
              ✕
            </button>
          </div>
        )}

        {/* STEP 0: CLUSTER (first run): create one, or join one */}
        {step === 0 && (
          <>
            <div className="setup-card-header">
              <h2>Cluster</h2>
              <p>
                A cluster is the backends that share one database, and the hosts and WebUIs that use them. Start a
                new one, or join one another WebUI invited you to.
              </p>
            </div>

            <div className="setup-card-body">
              <div className="setup-host-tiles" role="radiogroup" aria-label="Create or join a cluster">
                <button
                  type="button"
                  role="radio"
                  aria-checked={clusterChoice === 'create'}
                  className={`setup-host-tile${clusterChoice === 'create' ? ' is-selected' : ''}`}
                  disabled={Boolean(joinedCluster)}
                  onClick={() => setClusterChoice('create')}
                >
                  <svg className="setup-host-tile-icon" viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M12 2.5l8.5 4.75v9.5L12 21.5l-8.5-4.75v-9.5z" />
                    <path d="M12 8.5v7M8.5 12h7" />
                  </svg>
                  <strong>Create a cluster</strong>
                  <span>A new one, with its own PostgreSQL and Redis</span>
                </button>
                <button
                  type="button"
                  role="radio"
                  aria-checked={clusterChoice === 'join'}
                  className={`setup-host-tile${clusterChoice === 'join' ? ' is-selected' : ''}`}
                  onClick={() => setClusterChoice('join')}
                >
                  <svg className="setup-host-tile-icon" viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M10 14a4 4 0 0 0 5.66 0l3-3a4 4 0 0 0-5.66-5.66l-1 1" />
                    <path d="M14 10a4 4 0 0 0-5.66 0l-3 3a4 4 0 0 0 5.66 5.66l1-1" />
                  </svg>
                  <strong>Join a cluster</strong>
                  <span>One another WebUI invited you to</span>
                </button>
              </div>

              {clusterChoice === 'join' && !joinMessage && (
                <JoinClusterForm onJoined={(result) => void handleJoined(result)} />
              )}

              {joinMessage && (
                <div className="setup-test-result success" role="status">
                  <span className="icon">✓</span>
                  <div className="details">
                    <div>{joinMessage}</div>
                    {joinedCluster ? (
                      <div>
                        This WebUI is connected to {joinedCluster.name}. You can finish and open it now, or install
                        additional components on a host.
                      </div>
                    ) : (
                      <div>No backend of it can be reached from here yet, so nothing can be installed for it.</div>
                    )}
                  </div>
                </div>
              )}
            </div>

            <div className="setup-card-footer">
              {joinMessage ? (
                <>
                  <button
                    type="button"
                    className="btn-secondary btn-lg"
                    onClick={() => setStep(1)}
                  >
                    Install on a host
                  </button>
                  <a
                    className="btn-primary btn-lg"
                    href={joinedCluster ? connectionHome(joinedCluster.connectionId) : '/connections'}
                    onClick={(event) =>
                      followInApp(event, joinedCluster ? connectionHome(joinedCluster.connectionId) : '/connections')
                    }
                  >
                    Finish
                  </a>
                </>
              ) : (
                <>
                  <span />
                  <button
                    type="button"
                    className="btn-primary btn-lg"
                    disabled={clusterChoice !== 'create'}
                    onClick={() => setStep(1)}
                  >
                    Continue
                  </button>
                </>
              )}
            </div>
          </>
        )}

        {/* STEP 1: HOST */}
        {step === 1 && (
          <>
            <div className="setup-card-header">
              <h2>Host</h2>
              <p>Install on this machine, or on another one you reach over SSH.</p>
            </div>

            <div className="setup-card-body">
              <div className="setup-host-tiles" role="radiogroup" aria-label="Where to install">
                <button
                  type="button"
                  role="radio"
                  aria-checked={hostChoice === 'local'}
                  className={`setup-host-tile${hostChoice === 'local' ? ' is-selected' : ''}`}
                  onClick={chooseLocal}
                >
                  <svg className="setup-host-tile-icon" viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="3" y="4" width="18" height="12" rx="2" />
                    <path d="M8 20h8M12 16v4" />
                  </svg>
                  <strong>Local</strong>
                  <span>
                    This machine{environment?.local_available !== false && facts?.hostname && where === 'local'
                      ? ` (${facts.hostname})`
                      : ''}
                  </span>
                </button>
                <button
                  type="button"
                  role="radio"
                  aria-checked={hostChoice === 'remote'}
                  className={`setup-host-tile${hostChoice === 'remote' ? ' is-selected' : ''}`}
                  onClick={chooseRemote}
                >
                  <svg className="setup-host-tile-icon" viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="4" y="3" width="16" height="6" rx="1.5" />
                    <rect x="4" y="11" width="16" height="6" rx="1.5" />
                    <path d="M8 6h.01M8 14h.01M12 17v3M5 21h14" />
                  </svg>
                  <strong>Remote</strong>
                  <span>Another machine, over SSH</span>
                </button>
              </div>

              {hostChoice !== null && thisMachineOverSsh && (
                <p className="deploy-note" style={{ marginBottom: 'var(--space-3)' }}>
                  This WebUI runs in a container, so it reaches the machine it runs on over SSH, as{' '}
                  <code>host.docker.internal</code>. That machine needs an SSH server, and you sign
                  in as your own user.
                </p>
              )}

              {hostChoice !== null && where === 'ssh' && (
                <div className="connections-form" style={{ borderTop: 'none', paddingTop: 0 }}>
                  <div className="deploy-row">
                    <label>
                      <span>Host</span>
                      <input
                        value={host}
                        onChange={(event) => {
                          setHost(event.target.value);
                          setHostKey(null);
                          setHostKeyAccepted(false);
                          setDetection(null);
                        }}
                        placeholder="nas.example.test or 192.168.1.20"
                        required
                      />
                    </label>
                    <label className="deploy-port">
                      <span>Port</span>
                      <input
                        type="number"
                        value={port}
                        min={1}
                        max={65535}
                        onChange={(event) => {
                          setPort(Number(event.target.value) || 22);
                          setHostKey(null);
                          setHostKeyAccepted(false);
                          setDetection(null);
                        }}
                      />
                    </label>
                  </div>
                  <label>
                    <span>User</span>
                    <input
                      value={username}
                      onChange={(event) => setUsername(event.target.value)}
                      required
                      autoComplete="off"
                    />
                  </label>
                  <div className="deploy-choice">
                    <label className="connections-checkbox">
                      <input
                        type="radio"
                        checked={authMethod === 'password'}
                        onChange={() => setAuthMethod('password')}
                      />
                      <span>Password</span>
                    </label>
                    <label className="connections-checkbox">
                      <input
                        type="radio"
                        checked={authMethod === 'key'}
                        onChange={() => setAuthMethod('key')}
                      />
                      <span>Private key</span>
                    </label>
                  </div>
                  {authMethod === 'password' ? (
                    <label>
                      <span>SSH password</span>
                      <input
                        type="password"
                        value={password}
                        onChange={(event) => setPassword(event.target.value)}
                        autoComplete="off"
                      />
                    </label>
                  ) : (
                    <label>
                      <span>Private key</span>
                      <textarea
                        rows={4}
                        value={privateKey}
                        onChange={(event) => setPrivateKey(event.target.value)}
                        placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                        spellCheck={false}
                      />
                    </label>
                  )}
                  <small className="deploy-note">
                    Used only for this install, never stored. The WebUI then reaches the backend
                    with a key it generates, which can do nothing but forward to the backend&apos;s
                    port.
                  </small>

                  <div className="connections-actions">
                    {checkingHost && <span className="deploy-note">Fetching the host key…</span>}
                    {!checkingHost && !hostKey && host.trim() && error && (
                      <button type="button" className="connections-button" onClick={() => void checkHost()}>
                        Fetch the host key again
                      </button>
                    )}
                    {hostKey && hostKeyAccepted && (
                      <button
                        type="button"
                        className="connections-button"
                        disabled={detecting}
                        onClick={() => void runDetection()}
                      >
                        {detecting ? 'Detecting…' : 'Detect host'}
                      </button>
                    )}
                  </div>
                  {hostKey && (
                    <div className="deploy-hostkey">
                      <p>
                        {host.trim()} presented this {hostKey.algorithm} key. Does its fingerprint
                        match the host&apos;s own?
                      </p>
                      <code>{hostKey.fingerprint}</code>
                      <small>
                        On the host: <code>ssh-keygen -lf {hostKeyFile(hostKey.algorithm)}</code>
                      </small>
                      {hostKeyAccepted ? (
                        <span className="connections-status is-ok" role="status">
                          ✓ Fingerprint confirmed
                        </span>
                      ) : (
                        <div className="connections-actions">
                          <button
                            type="button"
                            className="connections-button is-primary"
                            onClick={() => setHostKeyAccepted(true)}
                          >
                            Yes, it matches
                          </button>
                          <span className="deploy-note">If it does not, do not go on: something else answered.</span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {hostChoice !== null && detecting && (
                <div className="setup-test-result pending" role="status">
                  <span className="icon">⋯</span>
                  <div className="details">Detecting host environment…</div>
                </div>
              )}

              {hostChoice !== null && facts && (
                <div className="setup-facts-card" aria-label="Detected host facts">
                  <div className="setup-facts-grid">
                    <div className="setup-fact-item">
                      <span className="setup-fact-label">Hostname</span>
                      <span className="setup-fact-value">{facts.hostname || 'unknown'}</span>
                    </div>
                    <div className="setup-fact-item">
                      <span className="setup-fact-label">OS / Arch</span>
                      <span className="setup-fact-value">
                        {facts.os_name} · {facts.architecture}
                      </span>
                    </div>
                    <div className="setup-fact-item">
                      <span className="setup-fact-label">Docker &amp; Compose</span>
                      <span className="setup-fact-value">
                        {facts.docker_version && facts.compose_version ? 'Ready' : 'Not installed'}
                      </span>
                    </div>
                    <div className="setup-fact-item">
                      <span className="setup-fact-label">Privileges</span>
                      <span className="setup-fact-value">
                        {facts.sudo_mode === 'none'
                          ? 'Docker group (no sudo)'
                          : facts.sudo_mode === 'passwordless'
                            ? 'Passwordless sudo'
                            : 'sudo password when needed'}
                      </span>
                    </div>
                    <div className="setup-fact-item">
                      <span className="setup-fact-label">Resources</span>
                      <span className="setup-fact-value">
                        {facts.memory_mb ?? '?'} MB RAM ·{' '}
                        {facts.home_free_mb != null
                          ? `${Math.round(facts.home_free_mb / 1024)} GB free`
                          : '? GB free'}
                      </span>
                    </div>
                    {detectedServicesList.length > 0 && (
                      <div className="setup-fact-item">
                        <span className="setup-fact-label">Detected services</span>
                        <span className="setup-fact-value">
                          {detectedServicesList.join(', ')}
                        </span>
                      </div>
                    )}
                    {unreachableStores.length > 0 && (
                      <div className="setup-fact-item">
                        <span className="setup-fact-label">Not reusable</span>
                        <span className="setup-fact-value">
                          {unreachableStores.join(', ')} (port not published on {targetHostname})
                        </span>
                      </div>
                    )}
                  </div>

                  {facts.warnings.length > 0 && (
                    <ul className="setup-warning-list" role="alert">
                      {facts.warnings.map((warning) => (
                        <li key={warning}>⚠ {warning}</li>
                      ))}
                    </ul>
                  )}

                  {(facts.existing_install || facts.existing_projects.length > 0) && (
                    <div className="setup-existing-box">
                      <strong>Existing UltimaScraper deployment detected</strong>
                      <span style={{ fontSize: 'var(--font-size-xs)' }}>
                        {facts.existing_install
                          ? `Found ${facts.existing_install.project} (${facts.existing_install.version || 'installed'}) in ${installDir}.`
                          : `Active Compose project(s): ${facts.existing_projects.join(', ')}.`}
                      </span>
                      <div className="connections-actions">
                        <button
                          type="button"
                          className="connections-button is-primary"
                          disabled={registeringExisting}
                          onClick={() => void handleRegisterExisting()}
                        >
                          {registeringExisting ? 'Connecting…' : 'Connect this install'}
                        </button>
                        {matchingDeployment && (
                          <button
                            type="button"
                            className="connections-button"
                            onClick={() => void handleRepairExisting(matchingDeployment)}
                          >
                            Repair
                          </button>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}

            </div>

            <div className="setup-card-footer">
              {clusterProp ? (
                <span />
              ) : (
                <button type="button" className="btn-secondary btn-lg" onClick={() => setStep(0)}>
                  Back
                </button>
              )}
              <button
                type="button"
                className="btn-primary btn-lg"
                disabled={hostChoice === null || !detection || detecting}
                onClick={() => setStep(2)}
              >
                Continue
              </button>
            </div>
          </>
        )}

        {/* STEP 2: COMPONENTS */}
        {step === 2 && (
          <>
            <div className="setup-card-header">
              <h2>Components</h2>
              <p>Choose which parts to install on {targetHostname} and which to reuse.</p>
            </div>

            <div className="setup-card-body">
              <div className="setup-component-list">
                {/* Backend (with worker) Card: two containers, one choice */}
                <div className="setup-component-card" data-testid="card-backend">
                  <div className="setup-component-header">
                    <h3>Backend</h3>
                    <span className="setup-form-hint">
                      {computeChoice(components) === 'worker'
                        ? 'A worker that runs jobs for a backend you already have'
                        : 'The API this WebUI talks to, with a worker that runs scrape and download jobs'}
                    </span>
                  </div>
                  <div className="setup-mode-options">
                    {COMPUTE_CHOICES.map((choice) => (
                      <button
                        key={choice}
                        type="button"
                        className={`setup-mode-option${computeChoice(components) === choice ? ' is-selected' : ''}`}
                        onClick={() => {
                          setComponents((prev: ComponentSelection) => {
                            const next = applyComputeChoice(prev, choice);
                            return lockStores ? withClusterStores(next) : next;
                          });
                          if ((choice === 'worker' || lockStores) && clusterStores?.available) {
                            applyClusterStoreDefaults(true);
                          }
                        }}
                      >
                        {COMPUTE_LABELS[choice]}
                      </button>
                    ))}
                  </div>
                  {computeChoice(components) === 'worker' && cluster && (
                    <div className="setup-form-hint" style={{ marginTop: 'var(--space-2)' }}>
                      Runs jobs for {cluster.name}.
                    </div>
                  )}
                  {computeChoice(components) === 'worker' && !cluster && (
                    <div className="setup-form-group" style={{ marginTop: 'var(--space-2)' }}>
                      <label className="setup-form-label" htmlFor="join-backend-select">
                        Backend to work for
                        <SetupHint text="Add workers on other hosts to run more jobs at once. This worker uses that backend's PostgreSQL and Redis." />
                      </label>
                      {connections.length > 0 ? (
                        <select
                          id="join-backend-select"
                          aria-label="Backend connection to join"
                          className="setup-form-input"
                          value={joinConnectionId}
                          onChange={(event) => setJoinConnectionId(event.target.value)}
                        >
                          {connections.map((conn) => (
                            <option key={conn.id} value={conn.id}>
                              {conn.name} ({conn.base_url})
                            </option>
                          ))}
                        </select>
                      ) : (
                        <div className="setup-disabled-reasons">
                          No backend is connected yet. Install one first, or connect one on the Backends page.
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* PostgreSQL Card */}
                <div className="setup-component-card" data-testid="card-postgres">
                  <div className="setup-component-header">
                    <h3>PostgreSQL</h3>
                    {components.backend === 'install' && components.worker === 'install' && (
                      <span className="setup-component-badge">Shared with Backend</span>
                    )}
                  </div>
                  <div className="setup-mode-options">
                    {(['install', 'existing', 'none'] as StoreMode[]).map((mode) => {
                      const allowed = cardRules.postgres.allowed.includes(mode);
                      const selected = components.postgres === mode;
                      const reason = cardRules.postgres.disabled_reasons[mode];
                      const label =
                        mode === 'existing' && cluster
                          ? "This cluster's"
                          : mode === 'existing'
                          ? localPgDetected
                            ? `Use existing (${targetHostname})`
                            : clusterStores?.available
                              ? "Cluster's"
                              : MODE_LABELS[mode]
                          : MODE_LABELS[mode];
                      return (
                        <button
                          key={mode}
                          type="button"
                          disabled={!allowed}
                          title={reason}
                          className={`setup-mode-option${selected ? ' is-selected' : ''}${!allowed ? ' is-disabled' : ''}`}
                          onClick={() => {
                            setComponents((prev: ComponentSelection) =>
                              applyComponentChange(prev, 'postgres', mode),
                            );
                            if (mode === 'existing' && clusterStores?.database) {
                              setDbConfig({
                                host: clusterStores.database.host,
                                port: clusterStores.database.port,
                                name: clusterStores.database.name,
                                username: clusterStores.database.username,
                                password: clusterStores.database.password,
                              });
                              setPgCheck(null);
                            }
                          }}
                        >
                          {label}
                        </button>
                      );
                    })}
                  </div>
                  {Object.entries(cardRules.postgres.disabled_reasons).map(([mode, reason]) => (
                    <div key={mode} className="setup-disabled-reasons">
                      {MODE_LABELS[mode as StoreMode]}: {reason}
                    </div>
                  ))}
                  {cluster && components.postgres === 'existing' && (
                    <div className="setup-form-hint" data-testid="cluster-postgres">
                      {cluster.name}&apos;s: {dbConfig.host}:{dbConfig.port}/{dbConfig.name}
                    </div>
                  )}
                  {cluster && components.backend === 'install' && components.postgres === 'install' && (
                    <div className="setup-warning-list">
                      <div>
                        ⚠ A backend with its own PostgreSQL starts a separate cluster instead of joining {cluster.name}.
                      </div>
                    </div>
                  )}
                  {storeOnlyHost && components.postgres === 'install' && (
                    <div className="setup-warning-list">
                      <div>
                        ⚠ Publishes PostgreSQL on the host network for other hosts. Restrict access
                        with a firewall.
                      </div>
                      <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
                        <span>Published port:</span>
                        <input
                          type="number"
                          aria-label="PostgreSQL published port"
                          className="setup-form-input"
                          style={{ width: 100 }}
                          value={postgresPort}
                          onChange={(event) => setPostgresPort(Number(event.target.value) || 5432)}
                        />
                      </label>
                    </div>
                  )}
                </div>

                {/* Redis Card */}
                <div className="setup-component-card" data-testid="card-redis">
                  <div className="setup-component-header">
                    <h3>Redis</h3>
                    {components.backend === 'install' && components.worker === 'install' && (
                      <span className="setup-component-badge">Shared with Backend</span>
                    )}
                  </div>
                  <div className="setup-mode-options">
                    {(['install', 'existing', 'none'] as StoreMode[]).map((mode) => {
                      const allowed = cardRules.redis.allowed.includes(mode);
                      const selected = components.redis === mode;
                      const reason = cardRules.redis.disabled_reasons[mode];
                      const label =
                        mode === 'existing' && cluster
                          ? "This cluster's"
                          : mode === 'existing'
                          ? localRedisDetected
                            ? `Use existing (${targetHostname})`
                            : clusterStores?.available
                              ? "Cluster's"
                              : MODE_LABELS[mode]
                          : MODE_LABELS[mode];
                      return (
                        <button
                          key={mode}
                          type="button"
                          disabled={!allowed}
                          title={reason}
                          className={`setup-mode-option${selected ? ' is-selected' : ''}${!allowed ? ' is-disabled' : ''}`}
                          onClick={() => {
                            setComponents((prev: ComponentSelection) =>
                              applyComponentChange(prev, 'redis', mode),
                            );
                            if (mode === 'existing' && clusterStores?.redis) {
                              setRedisConfig({
                                host: clusterStores.redis.host,
                                port: clusterStores.redis.port,
                                db: clusterStores.redis.db,
                                password: clusterStores.redis.password,
                                enabled: true,
                              });
                              setRedisCheck(null);
                            }
                          }}
                        >
                          {label}
                        </button>
                      );
                    })}
                  </div>
                  {Object.entries(cardRules.redis.disabled_reasons).map(([mode, reason]) => (
                    <div key={mode} className="setup-disabled-reasons">
                      {MODE_LABELS[mode as StoreMode]}: {reason}
                    </div>
                  ))}
                  {cluster && components.redis === 'existing' && (
                    <div className="setup-form-hint" data-testid="cluster-redis">
                      {cluster.name}&apos;s: {redisConfig.host}:{redisConfig.port}
                    </div>
                  )}
                  {storeOnlyHost && components.redis === 'install' && (
                    <div className="setup-warning-list">
                      <div>
                        ⚠ Publishes Redis on the host network for other hosts. Restrict access with
                        a firewall.
                      </div>
                      <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, marginTop: 6 }}>
                        <span>Published port:</span>
                        <input
                          type="number"
                          aria-label="Redis published port"
                          className="setup-form-input"
                          style={{ width: 100 }}
                          value={redisPort}
                          onChange={(event) => setRedisPort(Number(event.target.value) || 6379)}
                        />
                      </label>
                    </div>
                  )}
                </div>

                {/* WebUI Card */}
                <div className="setup-component-card" data-testid="card-webui">
                  <div className="setup-component-header">
                    <h3>WebUI</h3>
                    <span className="setup-form-hint">
                      {isLocalTarget
                        ? 'This WebUI is already running on this machine'
                        : 'Manage the remote host from this WebUI or install another WebUI there'}
                    </span>
                  </div>
                  <div className="setup-mode-options">
                    {(['reuse', 'install'] as WebUIMode[]).map((mode) => {
                      const allowed = cardRules.webui.allowed.includes(mode);
                      const selected = components.webui === mode;
                      const label =
                        mode === 'reuse'
                          ? isLocalTarget
                            ? 'This WebUI (already present)'
                            : 'Manage from this WebUI'
                          : isLocalTarget
                            ? 'Install another WebUI here'
                            : `Install WebUI on ${targetHostname}`;
                      return (
                        <button
                          key={mode}
                          type="button"
                          disabled={!allowed}
                          className={`setup-mode-option${selected ? ' is-selected' : ''}${!allowed ? ' is-disabled' : ''}`}
                          onClick={() => {
                            setComponents((prev: ComponentSelection) =>
                              applyComponentChange(prev, 'webui', mode),
                            );
                            if (mode === 'reuse') setConfirmExtraWebui(false);
                          }}
                        >
                          {label}
                        </button>
                      );
                    })}
                  </div>
                  {isLocalTarget && components.webui === 'install' && (
                    <label className="setup-skip-toggle" style={{ marginBottom: 0 }}>
                      <input
                        type="checkbox"
                        checked={confirmExtraWebui}
                        onChange={(event) => setConfirmExtraWebui(event.target.checked)}
                      />
                      <span>
                        Confirm: install an extra WebUI on port {extraWebuiPort}
                      </span>
                    </label>
                  )}
                </div>
              </div>

              {!clientOnly && !componentValidation.valid && componentValidation.message && (
                <div className="setup-test-result error" role="alert">
                  <span className="icon">✗</span>
                  <div className="details">{componentValidation.message}</div>
                </div>
              )}

              {clientOnly && cluster && (
                <div className="setup-test-result success" role="status">
                  <span className="icon">✓</span>
                  <div className="details">
                    This WebUI is already connected to {cluster.name}. No additional services need to be installed on {targetHostname}.
                  </div>
                </div>
              )}
            </div>

            <div className="setup-card-footer">
              <button
                type="button"
                className="btn-secondary btn-lg"
                onClick={() => setStep(1)}
              >
                Back
              </button>
              {clientOnly && cluster ? (
                onDone ? (
                  <button
                    type="button"
                    className="btn-primary btn-lg"
                    onClick={() => onDone(cluster.connectionId)}
                  >
                    Finish &amp; Open {cluster.name}
                  </button>
                ) : (
                  <a
                    className="btn-primary btn-lg"
                    href={connectionHome(cluster.connectionId)}
                    onClick={(event) => followInApp(event, connectionHome(cluster.connectionId))}
                  >
                    Finish &amp; Open {cluster.name}
                  </a>
                )
              ) : (
                <button
                  type="button"
                  className="btn-primary btn-lg"
                  disabled={!canLeaveComponents}
                  onClick={() => setStep(needsConnectionsStep ? 3 : 4)}
                >
                  Continue
                </button>
              )}
            </div>
          </>
        )}

        {/* STEP 3: CONNECTIONS (only when PostgreSQL or Redis is "existing") */}
        {step === 3 && (
          <>
            <div className="setup-card-header">
              <h2>Connections</h2>
              <p>Enter and check the existing services this deployment will use.</p>
            </div>

            <div className="setup-card-body">
              {clusterStores?.available && (
                <div className="setup-existing-box" style={{ marginBottom: 'var(--space-4)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--space-2)' }}>
                    <div>
                      <strong>Inherited from {clusterStores.source_backend_name || 'Cluster'}</strong>
                      <div style={{ fontSize: 'var(--font-size-xs)', color: 'var(--color-text-muted)' }}>
                        Connection details were pre-filled from your existing cluster setup.
                      </div>
                    </div>
                    <button
                      type="button"
                      className="connections-link"
                      onClick={() => {
                        applyClusterStoreDefaults(true);
                        setPgCheck(null);
                        setRedisCheck(null);
                      }}
                    >
                      Reset to cluster defaults
                    </button>
                  </div>
                </div>
              )}

              {components.postgres === 'existing' && (
                <div style={{ marginBottom: components.redis === 'existing' ? 'var(--space-6)' : 0 }}>
                  <h3 style={{ marginTop: 0, marginBottom: 'var(--space-3)' }}>PostgreSQL</h3>
                  <DatabaseConnectionFields
                    dbConfig={dbConfig}
                    onChange={(next) => {
                      if (next.host !== dbConfig.host || next.port !== dbConfig.port) {
                        setPgCheck(null);
                      }
                      setDbConfig(next);
                    }}
                  />
                  {(dbConfig.host === 'localhost' || dbConfig.host === '127.0.0.1') && (
                    <div className="setup-form-hint" style={{ marginBottom: 'var(--space-2)' }}>
                      Containers will reach {targetHostname}&apos;s PostgreSQL via{' '}
                      <code>host.docker.internal</code>.
                    </div>
                  )}
                  <button
                    type="button"
                    className="btn-secondary"
                    disabled={checkingPg || !dbConfig.host.trim()}
                    onClick={() => void handleCheckPostgres()}
                  >
                    {checkingPg ? 'Checking…' : 'Check PostgreSQL'}
                  </button>
                  {pgCheck && (
                    <div
                      className={`setup-test-result ${pgCheck.reachable ? 'success' : 'error'}`}
                    >
                      <span className="icon">{pgCheck.reachable ? '✓' : '✗'}</span>
                      <div className="details">
                        <div>{pgCheck.message}</div>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {components.redis === 'existing' && (
                <div>
                  <h3 style={{ marginTop: 0, marginBottom: 'var(--space-3)' }}>Redis</h3>
                  <RedisConnectionFields
                    redisConfig={redisConfig}
                    onChange={(next) => {
                      if (next.host !== redisConfig.host || next.port !== redisConfig.port) {
                        setRedisCheck(null);
                      }
                      setRedisConfig(next);
                    }}
                    showDbIndex={false}
                  />
                  {(redisConfig.host === 'localhost' || redisConfig.host === '127.0.0.1') && (
                    <div className="setup-form-hint" style={{ marginBottom: 'var(--space-2)' }}>
                      Containers will reach {targetHostname}&apos;s Redis via{' '}
                      <code>host.docker.internal</code>.
                    </div>
                  )}
                  <button
                    type="button"
                    className="btn-secondary"
                    disabled={checkingRedis || !redisConfig.host.trim()}
                    onClick={() => void handleCheckRedis()}
                  >
                    {checkingRedis ? 'Checking…' : 'Check Redis'}
                  </button>
                  {redisCheck && (
                    <div
                      className={`setup-test-result ${redisCheck.reachable ? 'success' : 'error'}`}
                    >
                      <span className="icon">{redisCheck.reachable ? '✓' : '✗'}</span>
                      <div className="details">
                        <div>{redisCheck.message}</div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="setup-card-footer">
              <button
                type="button"
                className="btn-secondary btn-lg"
                onClick={() => setStep(2)}
              >
                Back
              </button>
              <button
                type="button"
                className="btn-primary btn-lg"
                disabled={!existingPassedChecks}
                onClick={() => setStep(4)}
              >
                Continue
              </button>
            </div>
          </>
        )}

        {/* STEP 4: REVIEW & INSTALL */}
        {step === 4 && (
          <form onSubmit={handleStartInstall}>
            <div className="setup-card-header">
              <h2>Review &amp; Install</h2>
              <p>Review your deployment choices and start the installation.</p>
            </div>

            <div className="setup-card-body">
              <div className="setup-form-group">
                <label className="setup-form-label" htmlFor="deployment-name-input">
                  Name
                </label>
                <input
                  id="deployment-name-input"
                  className="setup-form-input"
                  value={name}
                  onChange={(event) => {
                    setName(event.target.value);
                    setNameEdited(true);
                  }}
                  placeholder={facts?.hostname || 'local'}
                  required
                  maxLength={60}
                />
              </div>

              {createsCluster && (
                <div className="setup-form-group">
                  <label className="setup-form-label" htmlFor="cluster-name-input">
                    Cluster name
                    <SetupHint text="This backend's new database starts a cluster: the backends that share it, and the hosts and WebUIs that join it later." />
                  </label>
                  <input
                    id="cluster-name-input"
                    className="setup-form-input"
                    value={clusterName}
                    onChange={(event) => setClusterName(event.target.value)}
                    required
                    maxLength={80}
                  />
                </div>
              )}

              {lockStores && (components.postgres === 'existing' || components.redis === 'existing') && (
                <div className="setup-summary" style={{ marginBottom: 'var(--space-4)' }} data-testid="cluster-store-checks">
                  {(
                    [
                      ['PostgreSQL', components.postgres, pgCheck, checkingPg, handleCheckPostgres],
                      ['Redis', components.redis, redisCheck, checkingRedis, handleCheckRedis],
                    ] as const
                  )
                    .filter(([, mode]) => mode === 'existing')
                    .map(([label, , check, checking, retry]) => (
                      <div className="setup-summary-row" key={label}>
                        <span className="setup-summary-label">{label}</span>
                        <span className="setup-summary-value">
                          {checking || !check
                            ? `Checking ${targetHostname} reaches it…`
                            : check.reachable
                              ? `✓ Reachable from ${targetHostname} (${check.host}:${check.port})`
                              : `✗ ${check.message}`}
                          {check && !check.reachable && !checking && (
                            <button type="button" className="connections-link" onClick={() => void retry()}>
                              {' '}Check again
                            </button>
                          )}
                        </span>
                      </div>
                    ))}
                </div>
              )}

              <ArchitectureDiagram plan={plannedInstall} />

              <div className="setup-summary" style={{ marginBottom: 'var(--space-4)' }}>
                <div className="setup-summary-row">
                  <span className="setup-summary-label">Target</span>
                  <span className="setup-summary-value mono">
                    {where === 'local'
                      ? `This machine (${facts?.hostname || 'local'})`
                      : `${username}@${host}:${port}`}
                  </span>
                </div>
                <div className="setup-summary-row">
                  <span className="setup-summary-label">Backend</span>
                  <span className="setup-summary-value">
                    {computeChoice(components) === 'backend'
                      ? 'Install here, with a worker'
                      : computeChoice(components) === 'worker'
                        ? `Worker only, for ${connections.find((conn) => conn.id === joinConnectionId)?.name ?? 'an existing backend'}`
                        : 'Not here'}
                  </span>
                </div>
                <div className="setup-summary-row">
                  <span className="setup-summary-label">PostgreSQL</span>
                  <span className="setup-summary-value">
                    {components.postgres === 'existing'
                      ? `${clusterStores?.available ? 'Cluster' : 'Existing'} (${dbConfig.username}@${dbConfig.host}:${dbConfig.port}/${dbConfig.name})`
                      : MODE_LABELS[components.postgres]}
                  </span>
                </div>
                <div className="setup-summary-row">
                  <span className="setup-summary-label">Redis</span>
                  <span className="setup-summary-value">
                    {components.redis === 'existing'
                      ? `${clusterStores?.available ? 'Cluster' : 'Existing'} (${redisConfig.host}:${redisConfig.port})`
                      : MODE_LABELS[components.redis]}
                  </span>
                </div>
                <div className="setup-summary-row">
                  <span className="setup-summary-label">WebUI</span>
                  <span className="setup-summary-value">
                    {components.webui === 'reuse' ? 'Reuse this WebUI' : 'Install WebUI'}
                  </span>
                </div>
              </div>

              {components.backend === 'install' && (
                <label className="setup-skip-toggle">
                  <input
                    type="checkbox"
                    checked={shareBackend}
                    onChange={(event) => setShareBackend(event.target.checked)}
                  />
                  <span>
                    Let other machines use this backend: it also serves HTTPS on port 8443, so WebUIs on other machines
                    can join its cluster with an invite
                  </span>
                </label>
              )}

              {facts && (!facts.docker_version || !facts.compose_version) && (
                <label className="setup-skip-toggle">
                  <input
                    type="checkbox"
                    checked={installDocker}
                    onChange={(event) => setInstallDocker(event.target.checked)}
                  />
                  <span>Install Docker if {targetHostname} does not have it</span>
                </label>
              )}

              {showSudoPasswordField && (
                <div className="setup-form-group">
                  <label className="setup-form-label" htmlFor="sudo-password-input">
                    sudo password
                  </label>
                  <input
                    id="sudo-password-input"
                    type="password"
                    className="setup-form-input"
                    value={sudoPassword}
                    onChange={(event) => setSudoPassword(event.target.value)}
                    autoComplete="off"
                    required
                  />
                  <div className="setup-form-hint">
                    Needed for: {needsSudoFor.join(', ')}. Never stored.
                  </div>
                </div>
              )}

              <details className="setup-advanced">
                <summary>Advanced</summary>
                <div style={{ marginTop: 'var(--space-3)', display: 'grid', gap: 'var(--space-3)' }}>
                  <div className="setup-form-group" style={{ marginBottom: 0 }}>
                    <label className="setup-form-label" htmlFor="install-dir-input">
                      Install folder
                    </label>
                    <input
                      id="install-dir-input"
                      className="setup-form-input"
                      value={installDir}
                      onChange={(event) => setInstallDir(event.target.value)}
                      spellCheck={false}
                    />
                  </div>
                  <div className="setup-form-row">
                    <div className="setup-form-group" style={{ marginBottom: 0 }}>
                      <label className="setup-form-label" htmlFor="image-source-select">
                        Image source
                      </label>
                      <select
                        id="image-source-select"
                        className="setup-form-input"
                        value={imageSource}
                        onChange={(event) => {
                          const source = event.target.value as ImageSource;
                          setImageSource(source);
                          if (!versionEdited) setVersion(versionForSource(source, detection, environment));
                        }}
                      >
                        <option value="copy">Copy from this server</option>
                        <option value="target">Already on {targetHostname}</option>
                        <option value="registry">Pull from a registry</option>
                      </select>
                    </div>
                    <div className="setup-form-group" style={{ marginBottom: 0 }}>
                      <label className="setup-form-label" htmlFor="image-version-input">
                        Version
                      </label>
                      <input
                        id="image-version-input"
                        className="setup-form-input"
                        value={version}
                        onChange={(event) => {
                          setVersion(event.target.value);
                          setVersionEdited(true);
                        }}
                        placeholder="0.1.0"
                      />
                    </div>
                  </div>
                  {imageSource === 'registry' && (
                    <div className="setup-form-group" style={{ marginBottom: 0 }}>
                      <label className="setup-form-label" htmlFor="image-registry-input">
                        Registry
                      </label>
                      <input
                        id="image-registry-input"
                        className="setup-form-input"
                        value={imagePrefix}
                        placeholder={DEFAULT_IMAGE_REGISTRY}
                        onChange={(event) => setImagePrefix(event.target.value)}
                        onBlur={() => setImagePrefix((prev) => normalizeImagePrefix(prev))}
                        spellCheck={false}
                      />
                      <div className="setup-form-hint" style={{ marginTop: 'var(--space-1)' }}>
                        Docker repository path; the image <code>ultimascraper</code> is pulled from under it. The official image is at <code>{DEFAULT_IMAGE_REGISTRY}/ultimascraper</code>. Protocols (https://) are stripped and names are lowercased automatically.
                      </div>
                    </div>
                  )}
                </div>
              </details>

              {runId && <RunLog events={installEvents} />}
            </div>

            <div className="setup-card-footer">
              <button
                type="button"
                className="btn-secondary btn-lg"
                disabled={installStatus?.state === 'running'}
                onClick={() => {
                  setRunId(null);
                  setStep(needsConnectionsStep ? 3 : 2);
                }}
              >
                Back
              </button>
              <button
                type="submit"
                className="btn-primary btn-lg"
                disabled={
                  startingInstall ||
                  installStatus?.state === 'running' ||
                  !name.trim() ||
                  !existingPassedChecks
                }
              >
                {installStatus?.state === 'running'
                  ? 'Installing…'
                  : installStatus?.state === 'failed'
                    ? 'Retry Install'
                    : 'Install'}
              </button>
            </div>
          </form>
        )}

        {/* STEP 5: CONFIGURE BACKEND */}
        {step === 5 && installedConnectionId && (
          <AppProviders key={installedConnectionId} connectionId={installedConnectionId}>
            <InlineBackendConfigurator
              onFinished={(warnings) => {
                setAuthWarnings(warnings);
                setStep(6);
              }}
            />
          </AppProviders>
        )}

        {/* STEP 6: DONE */}
        {step === 6 && (
          <>
            <div className="setup-card-header">
              <h2>{name || 'Deployment'} is ready</h2>
              <p>Your UltimaScraper deployment is installed and configured.</p>
            </div>

            <div className="setup-card-body">
              {authWarnings.length > 0 && (
                <div className="setup-error" style={{ marginBottom: 'var(--space-4)' }}>
                  <span>
                    Setup completed, but{' '}
                    {authWarnings.length === 1 ? 'one account' : `${authWarnings.length} accounts`}{' '}
                    could not be added:
                    <ul>
                      {authWarnings.map((warning) => (
                        <li key={warning}>{warning}</li>
                      ))}
                    </ul>
                  </span>
                </div>
              )}

              {storeConnection && <StoreConnectionDetails connection={storeConnection} />}

              <div className="setup-test-result success">
                <span className="icon">✓</span>
                <div className="details">
                  {installedConnectionId
                    ? `${name || 'Backend'} is connected and ready to use.`
                    : `${name || 'Deployment'} has finished installing.`}
                </div>
              </div>
            </div>

            <div className="setup-card-footer">
              {onDone ? (
                <button type="button" className="btn-secondary btn-lg" onClick={() => onDone(installedConnectionId)}>
                  Close
                </button>
              ) : (
                <span />
              )}
              {installedConnectionId && (
                <a
                  className="btn-primary btn-lg"
                  href={connectionHome(installedConnectionId)}
                  onClick={(event) =>
                    followInApp(event, connectionHome(installedConnectionId))
                  }
                >
                  Open {name || installedConnectionId}
                </a>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
