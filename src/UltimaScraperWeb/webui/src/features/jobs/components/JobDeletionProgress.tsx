import { useEffect, useRef } from 'react';
import type { Job } from '../../../api/types/jobs';
import './JobDeletionProgress.css';

export function JobDeletionProgress({ job, onClose, layout }: {
  job: Job;
  onClose: () => void;
  layout?: 'modal' | 'panel';
}) {
  const closeButton = useRef<HTMLButtonElement>(null);
  const isPanel = layout === 'panel';
  const progress = job.deletion_progress;
  const total = Math.max(progress?.total_stages ?? 10, 1);
  const completed = Math.min(progress?.completed_stages ?? 0, total);

  useEffect(() => {
    if (isPanel) return;
    const previous = document.activeElement as HTMLElement | null;
    closeButton.current?.focus();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); onClose(); }
      if (event.key === 'Tab') { event.preventDefault(); closeButton.current?.focus(); }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener('keydown', onKeyDown);
      if (previous?.isConnected) previous.focus();
    };
  }, [isPanel, onClose]);

  const content = (
    <section className="job-deletion-dialog" role={isPanel ? 'region' : 'dialog'}
      aria-modal={isPanel ? undefined : true} aria-label="Job deletion progress"
      onClick={(event) => event.stopPropagation()}>
      <header>
        <div><span className="job-deletion-kicker">Deleting job</span>
          <h2>{job.job_name || job.job_id}</h2>
          <code>{job.job_id}</code>
        </div>
        <button ref={closeButton} type="button" className="modal-close" aria-label="Close job details" onClick={onClose}>×</button>
      </header>
      <div className="job-deletion-summary" aria-live="polite">
        <div className="job-deletion-stage"><strong>{progress?.error ? 'Retrying cleanup' : progress?.table ? `Cleaning ${progress.table}` : 'Queued for cleanup'}</strong>
          <span>{completed} of {total} stages complete</span></div>
        <progress aria-label="Cleanup stages" max={total} value={completed} />
        <dl>
          <div><dt>Rows removed</dt><dd>{(progress?.rows ?? 0).toLocaleString()}</dd></div>
          <div><dt>Partitions dropped</dt><dd>{progress?.partitions_dropped ?? 0}</dd></div>
        </dl>
        {progress?.error && <p className="error-message">{progress.error}</p>}
      </div>
    </section>
  );
  return isPanel ? content : <div className="modal-overlay" onClick={onClose}>{content}</div>;
}
