import type { SettingsResponse } from '../../../api/types/settings';

interface NetworkSettingsSectionProps {
  settings: SettingsResponse;
  getNestedValue: (section: string, key: string) => unknown;
  getDeepNestedValue: (section: string, subsection: string, key: string) => unknown;
  onNestedChange: (section: string, key: string, value: unknown) => void;
  onDeepNestedChange: (
    section: string,
    subsection: string,
    key: string,
    value: unknown,
  ) => void;
}

interface CountFieldProps {
  id: string;
  label: string;
  description: string;
  min: number;
  value: number;
  fallback: number;
  onChange: (value: number) => void;
}

function CountField({ id, label, description, min, value, fallback, onChange }: CountFieldProps) {
  return (
    <div className="setting-item">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="number"
        min={min}
        value={value}
        onChange={(event) => {
          const parsed = parseInt(event.target.value, 10);
          onChange(Number.isNaN(parsed) || parsed < min ? fallback : parsed);
        }}
      />
      <span className="setting-description">{description}</span>
    </div>
  );
}

interface OptionalCountFieldProps {
  id: string;
  label: string;
  description: string;
  value: number | null;
  onChange: (value: number | null) => void;
}

/** Blank means automatic (null); otherwise a positive integer. */
function OptionalCountField({ id, label, description, value, onChange }: OptionalCountFieldProps) {
  return (
    <div className="setting-item">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        type="number"
        min="1"
        placeholder="Automatic"
        value={value ?? ''}
        onChange={(event) => {
          const parsed = parseInt(event.target.value, 10);
          onChange(Number.isNaN(parsed) || parsed < 1 ? null : parsed);
        }}
      />
      <span className="setting-description">{description}</span>
    </div>
  );
}

export function NetworkSettingsSection({
  settings,
  getNestedValue,
  getDeepNestedValue,
  onNestedChange,
  onDeepNestedChange,
}: NetworkSettingsSectionProps) {
  // An edited null (cleared field) must not fall back to the saved value.
  const optionalValue = (section: string, key: string, saved: number | null | undefined) => {
    const edited = getNestedValue(section, key);
    return edited !== undefined ? (edited as number | null) : (saved ?? null);
  };
  const jobCount = (key: keyof NonNullable<SettingsResponse['job_execution']>, fallback: number) =>
    ((getNestedValue('job_execution', key) as number | undefined)
      ?? (settings.job_execution?.[key] as number | undefined)
      ?? fallback);

  return (
    <div className="settings-section">
      <h2>Worker Pool</h2>

      <div className="setting-item checkbox">
        <label>
          <input
            type="checkbox"
            checked={
              (getNestedValue('worker_pool', 'enabled') as boolean)
              ?? settings.worker_pool?.enabled
              ?? false
            }
            onChange={(event) =>
              onNestedChange('worker_pool', 'enabled', event.target.checked)}
          />
          Enable Worker Pool
        </label>
      </div>

      <div className="setting-item">
        <label htmlFor="worker-size">Worker Pool Size</label>
        <input
          id="worker-size"
          type="number"
          min="1"
          max="50"
          value={(getNestedValue('worker_pool', 'size') as number) ?? settings.worker_pool?.size ?? 1}
          onChange={(event) =>
            onNestedChange('worker_pool', 'size', parseInt(event.target.value, 10))}
        />
      </div>

      <div className="setting-item">
        <label htmlFor="worker-max-claimed-jobs">Max Claimed Jobs</label>
        <input
          id="worker-max-claimed-jobs"
          type="number"
          min="0"
          max="100"
          value={
            (getNestedValue('worker_pool', 'max_claimed_jobs') as number)
            ?? settings.worker_pool?.max_claimed_jobs
            ?? 5
          }
          onChange={(event) => {
            const value = parseInt(event.target.value, 10);
            onNestedChange('worker_pool', 'max_claimed_jobs', Number.isNaN(value) ? 0 : value);
          }}
        />
        <span className="setting-description">0 means unlimited claimed jobs</span>
      </div>

      <OptionalCountField
        id="worker-task-concurrency"
        label="Tasks per Worker"
        description="Concurrent tasks each worker runs. Leave blank to derive it from enabled proxy capacity."
        value={optionalValue('worker_pool', 'task_concurrency', settings.worker_pool?.task_concurrency)}
        onChange={(value) => onNestedChange('worker_pool', 'task_concurrency', value)}
      />

      <OptionalCountField
        id="worker-claim-batch-size"
        label="Claim Batch Size"
        description="Tasks a worker reserves per claim, capped at the ledger batch. Leave blank to use the ledger batch."
        value={optionalValue('worker_pool', 'claim_batch_size', settings.worker_pool?.claim_batch_size)}
        onChange={(value) => onNestedChange('worker_pool', 'claim_batch_size', value)}
      />

      <h2>Job Execution</h2>

      <div className="setting-item">
        <label htmlFor="job-window-max-tasks">Execution Window Max Tasks</label>
        <input
          id="job-window-max-tasks"
          type="number"
          min="1"
          value={
            (getNestedValue('job_execution', 'window_max_tasks') as number)
            ?? settings.job_execution?.window_max_tasks
            ?? 1000
          }
          onChange={(event) => {
            const value = parseInt(event.target.value, 10);
            onNestedChange('job_execution', 'window_max_tasks', Number.isNaN(value) ? 1 : value);
          }}
        />
        <span className="setting-description">
          Maximum tasks resident in one execution window; applies to future refills.
        </span>
      </div>

      <div className="setting-item">
        <label htmlFor="job-refill-ready-threshold">Refill Ready Threshold</label>
        <input
          id="job-refill-ready-threshold"
          type="number"
          min="0"
          value={
            (getNestedValue('job_execution', 'refill_ready_threshold') as number)
            ?? settings.job_execution?.refill_ready_threshold
            ?? 0
          }
          onChange={(event) => {
            const value = parseInt(event.target.value, 10);
            onNestedChange('job_execution', 'refill_ready_threshold', Number.isNaN(value) ? 0 : value);
          }}
        />
        <span className="setting-description">
          Refill when ready tasks fall to this count. 0 keeps adaptive refill.
        </span>
      </div>

      <div className="setting-item">
        <label htmlFor="job-event-retention-hours">Event Retention (hours)</label>
        <input
          id="job-event-retention-hours"
          type="number"
          min="1"
          value={
            (getNestedValue('job_execution', 'event_retention_hours') as number)
            ?? settings.job_execution?.event_retention_hours
            ?? 168
          }
          onChange={(event) => {
            const value = parseInt(event.target.value, 10);
            onNestedChange('job_execution', 'event_retention_hours', Number.isNaN(value) || value < 1 ? 168 : value);
          }}
        />
        <span className="setting-description">
          How long delivered job events are kept. Events an enabled plugin has not read yet are always kept.
        </span>
      </div>

      <div className="setting-item">
        <label htmlFor="job-task-history-retention-days">Task History Retention (days)</label>
        <input
          id="job-task-history-retention-days"
          type="number"
          min="0"
          value={
            (getNestedValue('job_execution', 'task_history_retention_days') as number)
            ?? settings.job_execution?.task_history_retention_days
            ?? 3
          }
          onChange={(event) => {
            const value = parseInt(event.target.value, 10);
            onNestedChange('job_execution', 'task_history_retention_days', Number.isNaN(value) || value < 0 ? 3 : value);
          }}
        />
        <span className="setting-description">
          After this many days a finished job keeps only its failed tasks (and tasks that started other tasks). Its summary counts stay. 0 keeps all task history.
        </span>
      </div>

      <div className="setting-item">
        <label htmlFor="job-receipt-retention-minutes">Write Receipt Retention (minutes)</label>
        <input
          id="job-receipt-retention-minutes"
          type="number"
          min="15"
          value={
            (getNestedValue('job_execution', 'receipt_retention_minutes') as number)
            ?? settings.job_execution?.receipt_retention_minutes
            ?? 60
          }
          onChange={(event) => {
            const value = parseInt(event.target.value, 10);
            onNestedChange('job_execution', 'receipt_retention_minutes', Number.isNaN(value) || value < 15 ? 60 : value);
          }}
        />
        <span className="setting-description">
          How long committed database write receipts are kept for crash replay and late result delivery. Running jobs keep theirs until they finish. Minimum 15.
        </span>
      </div>

      <h2>Finished Job Cleanup</h2>

      <CountField
        id="job-terminal-reconcile-interval"
        label="Cleanup Interval (seconds)"
        description="How often finished jobs' Redis working sets are archived and cleared. Minimum 30."
        min={30}
        value={jobCount('terminal_reconcile_interval_seconds', 300)}
        fallback={300}
        onChange={(value) => onNestedChange('job_execution', 'terminal_reconcile_interval_seconds', value)}
      />

      <CountField
        id="job-terminal-reconcile-min-age"
        label="Cleanup Minimum Age (seconds)"
        description="A finished job is cleaned up only after it has been finished this long."
        min={0}
        value={jobCount('terminal_reconcile_min_age_seconds', 300)}
        fallback={300}
        onChange={(value) => onNestedChange('job_execution', 'terminal_reconcile_min_age_seconds', value)}
      />

      <CountField
        id="job-terminal-reconcile-batch"
        label="Jobs Cleaned per Cycle"
        description="Maximum finished jobs cleaned up in one cycle."
        min={1}
        value={jobCount('terminal_reconcile_batch_size', 2)}
        fallback={2}
        onChange={(value) => onNestedChange('job_execution', 'terminal_reconcile_batch_size', value)}
      />

      <CountField
        id="job-completed-retention"
        label="Completed Job Cache Retention (seconds)"
        description="Cached headers of completed jobs are removed after this age, once their history is saved. Job history stays available. 0 removes them at once."
        min={0}
        value={jobCount('completed_job_retention_seconds', 86400)}
        fallback={86400}
        onChange={(value) => onNestedChange('job_execution', 'completed_job_retention_seconds', value)}
      />

      <CountField
        id="job-completed-retention-batch"
        label="Completed Job Cache Batch Size"
        description="Cached job headers checked per cleanup cycle."
        min={1}
        value={jobCount('completed_job_retention_batch_size', 1000)}
        fallback={1000}
        onChange={(value) => onNestedChange('job_execution', 'completed_job_retention_batch_size', value)}
      />

      <h2>Guest Requests</h2>

      <div className="setting-item checkbox">
        <label>
          <input
            type="checkbox"
            checked={
              (getNestedValue('network', 'guest_session_pool') as boolean)
              ?? settings.network?.guest_session_pool
              ?? true
            }
            onChange={(event) =>
              onNestedChange('network', 'guest_session_pool', event.target.checked)}
          />
          Guest Session Pool
        </label>
        <span className="setting-description">
          Spread each proxy&apos;s requests over many guest sessions. OnlyFans limits each guest
          session to about 3 requests/s. Needs at least one connection per worker on every
          proxy; workers apply changes when they restart.
        </span>
      </div>

      <div className="setting-item">
        <label htmlFor="guest-route-rate-limit">Rate Limit per Proxy (requests/s)</label>
        <input
          id="guest-route-rate-limit"
          type="number"
          min="0"
          step="1"
          value={
            (getNestedValue('network', 'guest_route_rate_limit') as number)
            ?? settings.network?.guest_route_rate_limit
            ?? 35
          }
          onChange={(event) => {
            const value = parseFloat(event.target.value);
            onNestedChange('network', 'guest_route_rate_limit', Number.isNaN(value) ? 0 : value);
          }}
        />
        <span className="setting-description">
          Shared by all workers. OnlyFans rejects more than about 38/s from one IP. 0 disables;
          workers apply changes when they restart.
        </span>
      </div>

      <div className="setting-item">
        <label htmlFor="guest-lookup-timeout">Guest Lookup Timeout (seconds)</label>
        <input
          id="guest-lookup-timeout"
          type="number"
          min="0.5"
          step="0.5"
          value={
            (getNestedValue('network', 'guest_lookup_timeout') as number | string)
            ?? settings.network?.guest_lookup_timeout
            ?? 3.5
          }
          onChange={(event) => {
            const raw = event.target.value;
            if (raw === '') {
              onNestedChange('network', 'guest_lookup_timeout', '');
              return;
            }
            const value = parseFloat(raw);
            onNestedChange(
              'network',
              'guest_lookup_timeout',
              Number.isNaN(value) ? 3.5 : value,
            );
          }}
          onBlur={(event) => {
            const raw = event.target.value;
            const value = parseFloat(raw);
            if (raw === '' || Number.isNaN(value) || value < 0.5) {
              onNestedChange('network', 'guest_lookup_timeout', 3.5);
            }
          }}
        />
        <span className="setting-description">
          Maximum time to wait for guest profile lookup via proxy routes before timing out. Default is 3.5s.
          Increase this value (e.g. 5.0–8.0s) when using high-latency or geographically distant proxy endpoints.
        </span>
      </div>

      <h2>Download Concurrency</h2>

      <div className="setting-item">
        <label htmlFor="download-max-concurrency">Max Concurrency</label>
        <input
          id="download-max-concurrency"
          type="number"
          min="1"
          value={
            (getDeepNestedValue('network', 'downloads', 'max_concurrency') as number)
            ?? settings.network?.downloads?.max_concurrency
            ?? 64
          }
          onChange={(event) => {
            const value = parseInt(event.target.value, 10);
            onDeepNestedChange(
              'network',
              'downloads',
              'max_concurrency',
              Number.isNaN(value) ? 1 : value,
            );
          }}
        />
        <span className="setting-description">
          Maximum simultaneous transfer parts for each download task
        </span>
      </div>

      <div className="setting-item">
        <label htmlFor="download-per-domain">Per-Domain Concurrency</label>
        <input
          id="download-per-domain"
          type="number"
          min="1"
          value={
            (getDeepNestedValue('network', 'downloads', 'per_domain_concurrency') as number)
            ?? settings.network?.downloads?.per_domain_concurrency
            ?? 8
          }
          onChange={(event) => {
            const value = parseInt(event.target.value, 10);
            onDeepNestedChange(
              'network',
              'downloads',
              'per_domain_concurrency',
              Number.isNaN(value) ? 1 : value,
            );
          }}
        />
        <span className="setting-description">Limit concurrent downloads per host</span>
      </div>

      <div className="setting-item">
        <label htmlFor="download-head-concurrency">HEAD Concurrency</label>
        <input
          id="download-head-concurrency"
          type="number"
          min="1"
          value={
            (getDeepNestedValue('network', 'downloads', 'head_concurrency') as number)
            ?? settings.network?.downloads?.head_concurrency
            ?? 64
          }
          onChange={(event) => {
            const value = parseInt(event.target.value, 10);
            onDeepNestedChange(
              'network',
              'downloads',
              'head_concurrency',
              Number.isNaN(value) ? 1 : value,
            );
          }}
        />
        <span className="setting-description">Concurrent HEAD metadata requests</span>
      </div>

      <div className="setting-item">
        <label htmlFor="download-buffer-size">Buffer Size (bytes)</label>
        <input
          id="download-buffer-size"
          type="number"
          min="1024"
          value={
            (getDeepNestedValue('network', 'downloads', 'buffer_size_bytes') as number)
            ?? settings.network?.downloads?.buffer_size_bytes
            ?? 10485760
          }
          onChange={(event) => {
            const value = parseInt(event.target.value, 10);
            onDeepNestedChange(
              'network',
              'downloads',
              'buffer_size_bytes',
              Number.isNaN(value) ? 10485760 : value,
            );
          }}
        />
        <span className="setting-description">Target multipart size and merge buffer</span>
      </div>
    </div>
  );
}
