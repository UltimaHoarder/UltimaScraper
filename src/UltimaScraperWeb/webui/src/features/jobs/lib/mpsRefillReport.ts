import type { MPSRefillTraceEvent } from '../../../api/types/jobs';

export function formatMPSRefillReport(events: MPSRefillTraceEvent[] = []): string {
  const ordered = [...events].sort((a, b) => a.timestamp_ms - b.timestamp_ms);
  const latestControls = [...ordered].reverse().find((event) => event.stage !== 'ledger_archive' && event.controls)?.controls;
  const settings = latestControls
    ? '| Effective control | Value |\n| :--- | :--- |\n' + Object.entries(latestControls)
      .map(([key, value]) => `| ${key} | ${value ?? 'Unavailable'} |`).join('\n')
    : 'Effective controls unavailable; verify the materializer is running the instrumented version.';
  const previous = new Map<number, number>();
  const legacy = ordered.filter((event) => event.stage !== 'ledger_refill' && event.stage !== 'ledger_archive');
  const rows = legacy.map((event) => {
    const prior = previous.get(event.cycle);
    previous.set(event.cycle, event.timestamp_ms);
    return `| ${new Date(event.timestamp_ms).toISOString()} | ${event.cycle} | ${event.stage} | ${prior == null ? '—' : `${event.timestamp_ms - prior} ms`} | ${event.ready} / ${event.inflight} | ${event.ready_added ?? event.task_count ?? '—'} | ${event.reason ?? '—'} |`;
  });
  const ledger = ordered.filter((event) => event.stage === 'ledger_refill');
  const independentArchive = ordered.some((event) => event.controls?.materializer_version === 'ledger-refill-v3');
  const ledgerRows = ledger.map((event, index) => {
    const prior = ledger[index - 1];
    const gap = prior ? `${event.timestamp_ms - prior.timestamp_ms} ms` : '—';
    const milliseconds = (value?: number | null) => value == null ? '—' : `${value.toFixed(2)} ms`;
    return `| ${new Date(event.timestamp_ms).toISOString()} | ${gap} | ${event.ready} / ${event.inflight} | ${event.archived_tasks ?? '—'} / ${event.admitted_tasks ?? '—'} | ${event.controls?.terminal_resident_tasks ?? 'Unavailable'} | ${milliseconds(event.archive_ms)} | ${milliseconds(event.window_accounting_ms)} | ${milliseconds(event.refill_ms)} | ${milliseconds(event.pass_ms)} |`;
  });
  const ledgerReport = ledgerRows.length
    ? 'Ledger planner observations; intervals include dispatch and work between passes. ' + (independentArchive
      ? 'Execution capacity excludes completed results. Archival drains independently; its count ceiling and byte high-water mark apply backpressure.\n\n'
      : 'Completed resident records occupy the bounded window until archival commits.\n\n') + '| UTC time | Since prior pass | Ready / active | Archived / admitted | Terminal records still resident | Archive | Window accounting | Refill | Full pass |\n| :--- | ---: | :--- | :--- | ---: | ---: | ---: | ---: | ---: |\n' + ledgerRows.join('\n') + '\n\n'
    : '';
  const archiveRows = ordered.filter((event) => event.stage === 'ledger_archive').map((event) =>
    `| ${new Date(event.timestamp_ms).toISOString()} | ${event.archived_tasks ?? '—'} | ${event.archive_ms == null ? '—' : `${event.archive_ms.toFixed(2)} ms`} |`);
  const archiveReport = archiveRows.length
    ? 'Independent archive observations; these commits do not gate individual task completion or each refill pass.\n\n| UTC time | Archived tasks | Archive pass |\n| :--- | ---: | ---: |\n' + archiveRows.join('\n') + '\n\n'
    : '';
  return `### MPS Refill Diagnostics\n\n${settings}\n\n` + ledgerReport + archiveReport + (rows.length
    ? 'Latest trace events; timing gaps are within each cycle and may include uninstrumented work.\n\n| UTC time | Cycle | Stage | Since prior stage | Ready / active | Batch | Stop reason |\n| :--- | ---: | :--- | ---: | :--- | ---: | :--- |\n' + rows.join('\n')
    : ledgerRows.length || archiveRows.length ? '' : 'No refill trace events available for this job.');
}
