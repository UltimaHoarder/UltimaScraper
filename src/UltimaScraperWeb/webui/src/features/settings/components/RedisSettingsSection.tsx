import type { SettingsResponse } from '../../../api/types/settings';

interface RedisSettingsSectionProps {
  settings: SettingsResponse;
  getNestedValue: (section: string, key: string) => unknown;
  onNestedChange: (section: string, key: string, value: unknown) => void;
  redisTestResult: { success: boolean; message: string; latency_ms: number | null } | null;
}

export function RedisSettingsSection({
  settings,
  getNestedValue,
  onNestedChange,
  redisTestResult,
}: RedisSettingsSectionProps) {
  const redisEnabled = (getNestedValue('redis', 'enabled') as boolean) ?? settings.redis.enabled;
  const executionMode =
    (getNestedValue('backend', 'execution_mode') as string)
    ?? settings.backend?.execution_mode
    ?? 'distributed';

  const executionModeDescription = (() => {
    if (!redisEnabled) {
      return 'Enable Redis to access distributed modes';
    }
    switch (executionMode) {
      case 'local':
        return 'Jobs stay on this backend only (in-memory queue)';
      case 'distributed':
        return 'Multiple backends compete for jobs via Redis queue';
      case 'redis_metrics':
        return 'Redis for logs/metrics only, jobs stay local';
      default:
        return '';
    }
  })();

  return (
    <div className="settings-section">
      <h2>Redis Settings</h2>
      <p className="section-description">
        Changes are saved to the shared runtime environment and require a backend/worker
        restart. A password shown as bullets is kept unless you replace or clear it.
      </p>

      <div className="setting-item checkbox">
        <label>
          <input
            type="checkbox"
            checked={redisEnabled}
            onChange={(event) => onNestedChange('redis', 'enabled', event.target.checked)}
          />
          Enable Redis
        </label>
        <span className="setting-description">Enable Redis for distributed mode</span>
      </div>

      <div className="setting-item">
        <label htmlFor="redis-host">Redis Host</label>
        <input
          id="redis-host"
          type="text"
          value={(getNestedValue('redis', 'host') as string) ?? settings.redis.host}
          onChange={(event) => onNestedChange('redis', 'host', event.target.value)}
        />
      </div>

      <div className="setting-item">
        <label htmlFor="redis-port">Redis Port</label>
        <input
          id="redis-port"
          type="number"
          value={(getNestedValue('redis', 'port') as number) ?? settings.redis.port}
          onChange={(event) => onNestedChange('redis', 'port', parseInt(event.target.value, 10))}
        />
      </div>

      <div className="setting-item">
        <label htmlFor="redis-db">Redis Database</label>
        <input
          id="redis-db"
          type="number"
          min="0"
          max="15"
          value={(getNestedValue('redis', 'db') as number) ?? settings.redis.db}
          onChange={(event) => onNestedChange('redis', 'db', parseInt(event.target.value, 10))}
        />
      </div>

      <div className="setting-item">
        <label htmlFor="redis-password">Redis Password</label>
        <input
          id="redis-password"
          type="password"
          value={(getNestedValue('redis', 'password') as string) ?? settings.redis.password ?? ''}
          onChange={(event) => onNestedChange('redis', 'password', event.target.value || null)}
          placeholder="Leave empty for no password"
        />
      </div>

      <div className="setting-item">
        <label htmlFor="redis-retention">Completed Job Retention (seconds)</label>
        <input
          id="redis-retention"
          type="number"
          min="60"
          value={(getNestedValue('redis', 'completed_job_retention_seconds') as number) ?? 604800}
          onChange={(event) =>
            onNestedChange(
              'redis',
              'completed_job_retention_seconds',
              Math.max(60, parseInt(event.target.value, 10) || 60),
            )}
        />
        <span className="setting-description">
          How long completed/cancelled/failed jobs stay in Redis before cleanup (default:
          {' '}604800).
        </span>
      </div>

      {redisTestResult && (
        <div className="setting-item">
          <div className={`test-result ${redisTestResult.success ? 'success' : 'error'}`}>
            {redisTestResult.message}
            {redisTestResult.latency_ms !== null && (
              <span className="latency"> ({redisTestResult.latency_ms.toFixed(2)}ms)</span>
            )}
          </div>
        </div>
      )}
      <h2>Backend Settings</h2>

      <div className="setting-item">
        <label htmlFor="backend-id">Backend ID</label>
        <input
          id="backend-id"
          disabled
          type="text"
          value={(getNestedValue('backend', 'backend_id') as string) ?? settings.backend?.backend_id ?? ''}
          onChange={(event) => onNestedChange('backend', 'backend_id', event.target.value || null)}
          placeholder="Defaults to hostname"
        />
        <span className="setting-description">Unique identifier for this backend instance</span>
      </div>

      <div className="setting-item">
        <label htmlFor="execution-mode">Execution Mode</label>
        <select
          id="execution-mode"
          value={executionMode}
          onChange={(event) => onNestedChange('backend', 'execution_mode', event.target.value)}
          disabled={!redisEnabled}
        >
          <option value="local">Local (No Redis)</option>
          <option value="distributed" disabled={!redisEnabled}>
            Distributed (Job Sharing)
          </option>
          <option value="redis_metrics" disabled={!redisEnabled}>
            Redis Metrics Only
          </option>
        </select>
        <span className="setting-description">{executionModeDescription}</span>
      </div>
    </div>
  );
}
