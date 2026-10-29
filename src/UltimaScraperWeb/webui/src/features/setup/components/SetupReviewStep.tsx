import type {
  DatabaseConnectionRequest,
  RedisConnectionRequest,
  SetupProxy,
  StagingDirectory,
  SetupAuthRequest,
} from '../../../api/types/setup';
import { SetupHint } from './SetupHint';

interface SetupReviewStepProps {
  dbConfig: DatabaseConnectionRequest;
  skipDb: boolean;
  redisConfig: RedisConnectionRequest;
  /** host:port of the deployment's Redis when setup keeps using it. */
  configuredRedis: string | null;
  downloadDirs: string[];
  proxies: SetupProxy[];
  stagingDirectory: StagingDirectory | null;
  auths: SetupAuthRequest[];
  hostname: string;
  setHostname: (hostname: string) => void;
  /** Set when the deployment's BACKEND_ID fixes the instance name. */
  pinnedBackendId: string | null;
  onBack: () => void;
  onComplete: () => void;
  isCompleting: boolean;
}

export function SetupReviewStep({
  dbConfig,
  skipDb,
  redisConfig,
  configuredRedis,
  downloadDirs,
  proxies,
  stagingDirectory,
  auths,
  hostname,
  setHostname,
  pinnedBackendId,
  onBack,
  onComplete,
  isCompleting,
}: SetupReviewStepProps) {
  const activeDirs = downloadDirs.filter((dir) => dir.trim());
  const activeAuths = auths.filter((auth) => auth.curl_command.trim());

  return (
    <>
      <div className="setup-card-header">
        <h2>Review & Complete</h2>
        <p>Review your configuration before finishing setup.</p>
      </div>

      <div className="setup-card-body">
        <div className="setup-form-group">
          <label className="setup-form-label">
            Instance Hostname
            <SetupHint text="Settings are stored under this name. Keep it stable: a different name starts with an empty configuration." />
          </label>
          <input
            type="text"
            className="setup-form-input"
            value={pinnedBackendId ?? hostname}
            onChange={(event) => setHostname(event.target.value)}
            placeholder="my-scraper"
            readOnly={pinnedBackendId !== null}
          />
          <div className="setup-form-hint">
            {pinnedBackendId !== null
              ? 'Set by BACKEND_ID in this deployment. Change it there and restart to rename the instance.'
              : 'A friendly name for this instance (used in multi-backend setups).'}
          </div>
        </div>

        <div className="setup-summary">
          <div className="setup-summary-row">
            <span className="setup-summary-label">Database</span>
            {skipDb ? (
              <span className="setup-summary-value success">Configured by deployment</span>
            ) : (
              <span className="setup-summary-value success mono">
                {dbConfig.username}@{dbConfig.host}:{dbConfig.port}/{dbConfig.name}
              </span>
            )}
          </div>
          <div className="setup-summary-row">
            <span className="setup-summary-label">Redis</span>
            {configuredRedis ? (
              <span className="setup-summary-value success">
                Configured by deployment (<span className="mono">{configuredRedis}</span>)
              </span>
            ) : (
              <span className="setup-summary-value success mono">
                {redisConfig.host}:{redisConfig.port}/{redisConfig.db}
              </span>
            )}
          </div>
          <div className="setup-summary-row">
            <span className="setup-summary-label">Download dirs</span>
            {activeDirs.length > 0 ? (
              <span className="setup-summary-value mono">{activeDirs.join(', ')}</span>
            ) : (
              <span className="setup-summary-value muted">default</span>
            )}
          </div>
          <div className="setup-summary-row">
            <span className="setup-summary-label">Staging</span>
            {stagingDirectory && stagingDirectory.path.trim() ? (
              <span className="setup-summary-value mono">
                {stagingDirectory.path} [{stagingDirectory.usage.join(', ')}]
                {stagingDirectory.policy.length > 0 ? ` ${stagingDirectory.policy.join(', ')}` : ''}
              </span>
            ) : (
              <span className="setup-summary-value muted">disabled</span>
            )}
          </div>
          <div className="setup-summary-row">
            <span className="setup-summary-label">Proxies</span>
            {proxies.length > 0 ? (
              <span className="setup-summary-value mono">
                {proxies.map((proxy) => proxy.url).join(', ')}
              </span>
            ) : (
              <span className="setup-summary-value muted">none</span>
            )}
          </div>
          <div className="setup-summary-row">
            <span className="setup-summary-label">Accounts</span>
            <span className="setup-summary-value">{activeAuths.length} account(s) to add</span>
          </div>
          {hostname && (
            <div className="setup-summary-row">
              <span className="setup-summary-label">Hostname</span>
              <span className="setup-summary-value">{hostname}</span>
            </div>
          )}
        </div>
      </div>

      <div className="setup-card-footer">
        <button onClick={onBack} className="btn-secondary btn-lg">
          Back
        </button>
        <button onClick={onComplete} disabled={isCompleting} className="btn-success btn-lg">
          {isCompleting ? 'Saving…' : 'Complete Setup'}
        </button>
      </div>
    </>
  );
}
