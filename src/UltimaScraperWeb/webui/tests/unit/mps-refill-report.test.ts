import { expect, it } from 'vitest';
import { formatMPSRefillReport } from '../../src/features/jobs/lib/mpsRefillReport';

it('exports effective settings, per-cycle timing, and refill stop reasons', () => {
  const base = { ready: 0, inflight: 156, completed: 100, failed: 0, window_end: 20000 };
  const report = formatMPSRefillReport([
    { ...base, cycle: 2, timestamp_ms: 4000, stage: 'refill_stopped', reason: 'global_byte_budget' },
    { ...base, cycle: 1, timestamp_ms: 1000, stage: 'runtime_controls', controls: { window_tasks: 20000, refill_ready_threshold: 10000, materializer_version: 'trace-v2' } },
    { ...base, cycle: 2, timestamp_ms: 3000, stage: 'materializer_started' },
    { ...base, cycle: 1, timestamp_ms: 2000, stage: 'archive_finished', task_count: 5000 },
  ]);
  expect(report).toContain('| window_tasks | 20000 |');
  expect(report).toContain('| refill_ready_threshold | 10000 |');
  expect(report).toContain('global_byte_budget');
  expect(report.match(/1000 ms/g)).toHaveLength(2);
});

it('explicitly reports absent trace evidence', () => {
  expect(formatMPSRefillReport()).toContain('No refill trace events available');
  expect(formatMPSRefillReport()).toContain('Effective controls unavailable');
});

it('exports ledger admission, archive timing and retained terminal pressure', () => {
  const base = { cycle: 0, ready: 512, inflight: 335, completed: 0, failed: 0, window_end: 0, stage: 'ledger_refill' };
  const report = formatMPSRefillReport([
    { ...base, timestamp_ms: 1000, archived_tasks: 512, admitted_tasks: 512, archive_ms: 825.19, refill_ms: 221.99, pass_ms: 1501.07, controls: { resident_tasks: 20000, terminal_resident_tasks: 19153 } },
    { ...base, timestamp_ms: 3400, archived_tasks: 512, admitted_tasks: 512, pass_ms: 1490 },
  ]);
  expect(report).toContain('512 / 512');
  expect(report).toContain('19153');
  expect(report).toContain('825.19 ms');
  expect(report).toContain('2400 ms');
  expect(report).toContain('1501.07 ms');
  expect(report).toContain('Unavailable');
  expect(report).not.toContain('No refill trace events');
});

it('distinguishes independent archival from execution capacity', () => {
  const base = { cycle: 0, ready: 512, inflight: 335, completed: 0, failed: 0, window_end: 0 };
  const report = formatMPSRefillReport([
    { ...base, stage: 'ledger_refill', timestamp_ms: 1000, admitted_tasks: 512, controls: { materializer_version: 'ledger-refill-v3', terminal_task_limit: 40000 } },
    { ...base, stage: 'ledger_archive', timestamp_ms: 1200, archived_tasks: 2048, archive_ms: 100, controls: { materializer_version: 'ledger-archive-v3' } },
  ]);
  expect(report).toContain('Execution capacity excludes completed results');
  expect(report).toContain('Independent archive observations');
  expect(report).toContain('40000');
  expect(report).toContain('2048');
  expect(report).not.toContain('occupy the bounded window until archival');
  expect(report).not.toContain('Latest trace events');
});
