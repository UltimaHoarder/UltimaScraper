import { useEffect, useState } from 'react';
import { getTaskMediaEvidence, type TaskMediaEvidencePage } from '../../../api/jobs';
import { getJobTaskResultFileUrl } from '../../../api/media';
import type { TaskDetail } from '../../../api/types/jobs';
import './TaskEvidencePages.css';

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function EvidenceReader({ jobId, taskId, selectionId, kind }: {
  jobId: string;
  taskId: string;
  selectionId: string;
  kind: 'download_results' | 'errors';
}) {
  const [open, setOpen] = useState(false);
  const [after, setAfter] = useState(-1);
  const [page, setPage] = useState<TaskMediaEvidencePage | null>(null);
  const [error, setError] = useState('');

  // Clear the previous page whenever a different request starts.
  const requestKey = open ? `${jobId}|${taskId}|${selectionId}|${kind}|${after}` : null;
  const [previousRequestKey, setPreviousRequestKey] = useState(requestKey);
  if (requestKey !== previousRequestKey) {
    setPreviousRequestKey(requestKey);
    if (requestKey !== null) {
      setPage(null);
      setError('');
    }
  }

  useEffect(() => {
    if (!open) return;
    const abort = new AbortController();
    void getTaskMediaEvidence(jobId, taskId, selectionId, kind, after, abort.signal)
      .then((value) => { if (!abort.signal.aborted) setPage(value); })
      .catch((reason: unknown) => {
        if (!abort.signal.aborted) setError(reason instanceof Error ? reason.message : 'Unable to load report');
      });
    return () => abort.abort();
  }, [open, after, jobId, taskId, selectionId, kind]);

  return (
    <details className="jdm-runbook-evidence" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>{kind === 'errors' ? 'Complete scrape error report' : 'Complete file report'}</summary>
      {open ? <>
        {error ? <p role="alert">{error}</p> : null}
        {!page && !error ? <p role="status">Loading report…</p> : null}
        {page?.items.length === 0 ? <p>No entries have been recorded.</p> : null}
        {page ? <ol start={(page.ordinals[0] ?? 0) + 1}>
          {page.items.map((item, index) => {
            const entry = record(item);
            const ordinal = page.ordinals[index];
            return <li key={ordinal}>
              {entry ? <>
                <strong>{String(entry.status ?? 'Recorded')} · media {String(entry.media_id ?? '')}</strong>
                {typeof entry.path === 'string' ? <p>
                  <a href={getJobTaskResultFileUrl(jobId, taskId, ordinal)} target="_blank" rel="noreferrer">
                    Open recorded file
                  </a>
                </p> : null}
                <details><summary>Result details</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(entry, null, 2)}</pre></details>
              </> : String(item)}
            </li>;
          })}
        </ol> : null}
        <div className="jdm-runbook-media-actions">
          <button type="button" className="btn btn-secondary" disabled={after === -1}
            onClick={() => setAfter(-1)}>First page</button>
          <button type="button" className="btn btn-secondary" disabled={page?.next_cursor == null}
            onClick={() => { if (page?.next_cursor != null) setAfter(page.next_cursor); }}>Next page</button>
        </div>
      </> : null}
    </details>
  );
}

export function TaskEvidencePages({ jobId, task }: { jobId: string; task: TaskDetail }) {
  const output = record(record(task.result)?.output);
  const download = record(output?.media_evidence);
  const scrape = record(output?.media_selection);
  const reference = download ?? scrape;
  const selectionId = reference?.selection_id;
  if (typeof selectionId !== 'string' || !task.task_id) return null;
  const kind = download ? 'download_results' : 'errors';
  return <EvidenceReader key={`${task.task_id}:${selectionId}`} jobId={jobId} taskId={task.task_id}
    selectionId={selectionId} kind={kind} />;
}
