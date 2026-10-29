import { useCallback, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { completeSetup, getSetupStatus, testDatabaseConnection } from '../../../api/setup';
import type {
  DRMConfig,
  DatabaseConnectionRequest,
  DatabaseConnectionResponse,
  NetworkConfig,
  RedisConnectionRequest,
  StagingDirectory,
  SetupAuthRequest,
  SetupStatusResponse,
} from '../../../api/types/setup';
import { SetupAuthsStep } from './SetupAuthsStep';
import { SetupDatabaseStep } from './SetupDatabaseStep';
import { SetupDrmStep } from './SetupDrmStep';
import { SetupRedisStep } from './SetupRedisStep';
import { SetupReviewStep } from './SetupReviewStep';
import { SetupStepIndicator } from './SetupStepIndicator';
import { SetupStorageNetworkStep } from './SetupStorageNetworkStep';

type SetupStepId = 'database' | 'redis' | 'storage' | 'drm' | 'auths' | 'review';

export function SetupPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [stepId, setStepId] = useState<SetupStepId | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [authWarnings, setAuthWarnings] = useState<string[] | null>(null);

  // Null until the user chooses; defaults to the deployment's connection.
  const [useConfiguredDb, setUseConfiguredDb] = useState<boolean | null>(null);
  const [dbConfig, setDbConfig] = useState<DatabaseConnectionRequest>({
    host: 'localhost',
    port: 5432,
    name: 'ultima_archive',
    username: 'ultimascraper',
    password: '',
    ssh: {
      port: 22,
      active: false,
    },
  });
  const [dbTestResult, setDbTestResult] = useState<DatabaseConnectionResponse | null>(null);

  const [redisConfig, setRedisConfig] = useState<RedisConnectionRequest>({
    host: 'localhost',
    port: 6379,
    db: 0,
    password: '',
    enabled: true,
  });

  const [downloadDirs, setDownloadDirs] = useState<string[]>(['']);
  // Download tuning keeps its defaults; it lives in Settings > Network.
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
  const hasConfiguredDatabase = Boolean(setupStatus?.has_database);
  const skipDb = hasConfiguredDatabase && (useConfiguredDb ?? true);
  const setSkipDb = (value: boolean) => setUseConfiguredDb(value);
  // Null until the user chooses; defaults to the deployment's Redis.
  const [useConfiguredRedisChoice, setUseConfiguredRedis] = useState<boolean | null>(null);
  const redisTarget = setupStatus?.redis_target ?? null;
  const useConfiguredRedis = Boolean(redisTarget) && (useConfiguredRedisChoice ?? true);

  const visibleSteps: { id: SetupStepId; label: string }[] = [
    ...(!hasConfiguredDatabase ? [{ id: 'database' as const, label: 'Database' }] : []),
    ...(!redisTarget ? [{ id: 'redis' as const, label: 'Redis' }] : []),
    { id: 'storage', label: 'Storage' },
    { id: 'drm', label: 'DRM' },
    { id: 'auths', label: 'Accounts' },
    { id: 'review', label: 'Review' },
  ];
  const activeStepId =
    stepId && visibleSteps.some((item) => item.id === stepId) ? stepId : visibleSteps[0].id;
  const activeStepIndex = Math.max(
    0,
    visibleSteps.findIndex((item) => item.id === activeStepId),
  );
  const goNext = () => {
    const next = visibleSteps[activeStepIndex + 1];
    if (next) setStepId(next.id);
  };
  const goBack =
    activeStepIndex > 0
      ? () => {
          const prev = visibleSteps[activeStepIndex - 1];
          if (prev) setStepId(prev.id);
        }
      : undefined;

  const testDbMutation = useMutation({
    mutationFn: (cfg: DatabaseConnectionRequest) => testDatabaseConnection(cfg),
    onSuccess: (result) => setDbTestResult(result),
    onError: (err: Error) =>
      setDbTestResult({ success: false, message: err.message, latency_ms: null }),
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
        database: skipDb ? null : dbConfig,
        // Keeping the deployment's Redis leaves its settings untouched.
        redis: useConfiguredRedis ? null : redisConfig,
        drm: drmConfig,
        network: networkConfig,
        auths: activeAuths,
        download_directories: activeDirs,
        staging_directories: activeStagingDirectories,
        hostname: hostname || null,
      });
    },
    onSuccess: async (result) => {
      queryClient.invalidateQueries({ queryKey: ['settings'] });
      queryClient.invalidateQueries({ queryKey: ['setup-status'] });
      // The cached bootstrap still says "not configured"; refresh it first, or
      // the backend's setup guard sends the next page back to /setup for a moment.
      await queryClient.refetchQueries({ queryKey: ['system-bootstrap'] });
      const authErrors = result.auth_errors ?? [];
      if (authErrors.length > 0) {
        // Setup is complete; keep the page so the failures are visible.
        setAuthWarnings(authErrors);
        return;
      }
      navigate('/', { replace: true });
    },
    onError: (err: Error) => setError(err.message || 'Setup failed'),
  });

  const handleTestDb = useCallback(() => {
    setDbTestResult(null);
    testDbMutation.mutate(dbConfig);
  }, [dbConfig, testDbMutation]);

  return (
    <div className="setup-page">
      <div className="setup-header">
        <img className="setup-logo" src="/favicon.svg" alt="UltimaScraper" />
        <h1>Welcome to UltimaScraper</h1>
        <p>Let&apos;s get your environment set up</p>
      </div>

      <SetupStepIndicator
        current={activeStepIndex + 1}
        labels={visibleSteps.map((item) => item.label)}
      />

      <div className="setup-card">
        {authWarnings && (
          <div className="setup-error" style={{ margin: 'var(--space-5) var(--space-6) 0' }}>
            <span>
              Setup completed, but {authWarnings.length === 1 ? 'one account' : `${authWarnings.length} accounts`}{' '}
              could not be added. Add {authWarnings.length === 1 ? 'it' : 'them'} again from Accounts.
              <ul>
                {authWarnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </span>
            <button className="setup-error-dismiss" onClick={() => navigate('/', { replace: true })}>
              Continue
            </button>
          </div>
        )}

        {error && (
          <div className="setup-error" style={{ margin: 'var(--space-5) var(--space-6) 0' }}>
            <span>{error}</span>
            <button className="setup-error-dismiss" onClick={() => setError(null)}>
              ✕
            </button>
          </div>
        )}

        {activeStepId === 'database' && (
          <SetupDatabaseStep
            dbConfig={dbConfig}
            setDbConfig={(cfg) => {
              setDbConfig(cfg);
              setDbTestResult(null);
            }}
            dbTestResult={dbTestResult}
            onTest={handleTestDb}
            isTesting={testDbMutation.isPending}
            onNext={goNext}
            skipDb={skipDb}
            setSkipDb={(value) => {
              setSkipDb(value);
              if (value) setDbTestResult(null);
            }}
            hasConfiguredDatabase={hasConfiguredDatabase}
          />
        )}

        {activeStepId === 'redis' && (
          <SetupRedisStep
            redisConfig={redisConfig}
            setRedisConfig={setRedisConfig}
            redisTarget={redisTarget}
            useConfigured={useConfiguredRedis}
            setUseConfigured={setUseConfiguredRedis}
            onBack={goBack}
            onNext={goNext}
          />
        )}

        {activeStepId === 'storage' && (
          <SetupStorageNetworkStep
            downloadDirs={downloadDirs}
            setDownloadDirs={setDownloadDirs}
            stagingDirectory={stagingDirectory}
            setStagingDirectory={setStagingDirectory}
            networkConfig={networkConfig}
            setNetworkConfig={setNetworkConfig}
            dataDirectory={setupStatus?.data_directory ?? ''}
            onBack={goBack}
            onNext={goNext}
          />
        )}

        {activeStepId === 'drm' && (
          <SetupDrmStep
            drmConfig={drmConfig}
            setDrmConfig={setDrmConfig}
            onBack={goBack ?? (() => undefined)}
            onNext={goNext}
          />
        )}

        {activeStepId === 'auths' && (
          <SetupAuthsStep
            auths={auths}
            setAuths={setAuths}
            availableProxies={networkConfig.proxies.map((proxy) => proxy.url)}
            onBack={goBack ?? (() => undefined)}
            onNext={goNext}
          />
        )}

        {activeStepId === 'review' && (
          <SetupReviewStep
            dbConfig={dbConfig}
            skipDb={skipDb}
            redisConfig={redisConfig}
            configuredRedis={useConfiguredRedis ? redisTarget : null}
            downloadDirs={downloadDirs}
            proxies={networkConfig.proxies}
            stagingDirectory={stagingDirectory}
            auths={auths}
            hostname={hostname}
            setHostname={setHostname}
            pinnedBackendId={setupStatus?.backend_id ?? null}
            onBack={goBack ?? (() => undefined)}
            onComplete={() => completeMutation.mutate()}
            isCompleting={completeMutation.isPending}
          />
        )}
      </div>
    </div>
  );
}
