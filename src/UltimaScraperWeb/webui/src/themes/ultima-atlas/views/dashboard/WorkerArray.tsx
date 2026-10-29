import { useState } from 'react';
import { Link } from 'react-router-dom';
import type { WorkerInfo } from '../../../../api/types/system';

export function WorkerArray({ workers }: { workers: WorkerInfo[] }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = workers.find((worker) => worker.worker_id === selectedId);
  return (
    <div className="atlas-worker-array">
      <div className="atlas-worker-legend"><span className="is-busy">Busy</span><span className="is-idle">Idle</span><span className="is-offline">Offline</span><Link to="/system">System / All workers</Link></div>
      <div className="atlas-worker-units" aria-label="Reported worker units">
        {workers.map((worker, index) => <button type="button" key={worker.worker_id} className={`is-${worker.status}`} title={`${worker.worker_id}: ${worker.status}`} aria-label={`${worker.worker_id}: ${worker.status}`} aria-pressed={worker.worker_id === selectedId} onClick={() => setSelectedId(worker.worker_id)}><i aria-hidden="true" /><span>{String(index + 1).padStart(3, '0')}</span></button>)}
      </div>
      {selected && <section className="atlas-worker-dossier" aria-label="Worker unit details" aria-live="polite">
        <header><span>WORKER UNIT</span><button type="button" onClick={() => setSelectedId(null)} aria-label="Close worker details">X</button></header>
        <strong>{selected.worker_id}</strong>
        <dl><div><dt>State</dt><dd>{selected.status}</dd></div><div><dt>Completed jobs</dt><dd>{selected.jobs_completed.toLocaleString()}</dd></div><div><dt>Assigned operation</dt><dd>{selected.current_job || 'None'}</dd></div></dl>
      </section>}
    </div>
  );
}
