import { describe, expect, it } from 'vitest';
import { applicationSettingsPayload, isProtectedSettingKey } from '../../src/api/settings';
import type { SettingsUpdate } from '../../src/api/types/settings';

describe('configuration ownership', () => {
  it('keeps application edits and revision while removing runtime and response fields', () => {
    const settings = {
      hostname: 'deployment-host', redis: { host: 'fixture', port: 6379, db: 0, password: 'runtime-secret', enabled: true },
      security: { allow_docs: false }, is_configured: true, config_version: 7,
      configuration_source: 'database', expected_version: 7,
      backend: { backend_id: 'deployment-host', execution_mode: 'local' },
      infinite_loop: false, worker_pool: { enabled: true, size: 9, sites: ['onlyfans'], max_claimed_jobs: 2 },
    } as SettingsUpdate;
    expect(applicationSettingsPayload(settings)).toEqual({
      expected_version: 7, backend: { execution_mode: 'local' },
      infinite_loop: false, worker_pool: { enabled: true, size: 9, sites: ['onlyfans'], max_claimed_jobs: 2 },
    });
    expect(settings.backend?.backend_id).toBe('deployment-host');
  });

  it('includes job execution controls so execution window edits are saved', () => {
    const settings = {
      expected_version: 7,
      job_execution: { window_max_tasks: 10000, refill_ready_threshold: 0 },
    } as SettingsUpdate;
    expect(applicationSettingsPayload(settings)).toEqual({
      expected_version: 7,
      job_execution: { window_max_tasks: 10000, refill_ready_threshold: 0 },
    });
  });

  it.each(['config', 'config_scope', 'db.connection', 'redis.host', 'download.directories', 'network.config'])('protects %s from the raw editor', key => {
    expect(isProtectedSettingKey(key)).toBe(true);
  });

  it('allows independent custom rows', () => {
    expect(isProtectedSettingKey('custom.example')).toBe(false);
  });
});
