import type { DashboardMockModel } from './dashboardMockModel';

const STAGES = ['Discovering', 'Authenticating', 'Downloading', 'Checksumming'] as const;

export function WorkloadRunwayConcept({ model }: { model: DashboardMockModel }) {
  const { jobs, selectedJob, setSelectedJobId, kpis } = model;
  const selectedPct = Math.round(
    ((selectedJob.completedTasks + selectedJob.failedTasks) / Math.max(selectedJob.totalTasks, 1)) * 100
  );

  return (
    <section className="dbm-concept dbm-workload-runway" aria-label="Workload & Queue Runway">
      <div className="dbm-runway-split">
        {/* Left: Active Jobs Queue Runway */}
        <article className="dbm-panel">
          <header className="dbm-panel-head">
            <div>
              <span className="dbm-eyebrow">WORKLOAD RUNWAY // {kpis.runningJobs} EXECUTING · {kpis.queuedJobs} QUEUED</span>
              <h3>Batch Operations &amp; ETA Forecast</h3>
            </div>
            <span className="dbm-badge">{kpis.totalItemsPerSec} items/s</span>
          </header>

          <div className="dbm-job-cards">
            {jobs.map((job) => {
              const pct = Math.round(((job.completedTasks + job.failedTasks) / Math.max(job.totalTasks, 1)) * 100);
              const isSelected = job.id === selectedJob.id;
              return (
                <div
                  key={job.id}
                  className={`dbm-job-row is-${job.status} ${isSelected ? 'is-selected' : ''}`}
                  onClick={() => setSelectedJobId(job.id)}
                >
                  <div className="dbm-job-row-top">
                    <span className={`dbm-pill is-${job.status}`}>{job.status}</span>
                    <button
                      type="button"
                      className="dbm-row-select-btn"
                      aria-pressed={isSelected}
                      onClick={() => setSelectedJobId(job.id)}
                    >
                      <code>{job.id}</code>
                    </button>
                    <small>{job.site} · {job.type}</small>
                    <div className="dbm-job-actions" onClick={(e) => e.stopPropagation()}>
                      {job.status === 'failed' ? (
                        <button type="button" className="dbm-mini-btn is-accent" onClick={() => model.retryFailedJob(job.id)}>
                          Retry Failed
                        </button>
                      ) : (
                        <button type="button" className="dbm-mini-btn" onClick={() => model.toggleJobPause(job.id)}>
                          {job.status === 'running' ? 'Pause' : 'Resume'}
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="dbm-job-row-title">
                    <strong>{job.name}</strong>
                    <span>{pct}%</span>
                  </div>
                  <div className="dbm-progress-bar">
                    <div style={{ width: `${pct}%` }} />
                  </div>
                  <div className="dbm-job-row-meta">
                    <span>{job.completedTasks.toLocaleString()} done · {job.failedTasks} failed</span>
                    <span>Stage: {job.currentStage}</span>
                    <span>{job.writeMbPerSec} MB/s</span>
                  </div>
                </div>
              );
            })}
          </div>
        </article>

        {/* Right: Selected Job Stage Breakdown & Telemetry Inspector */}
        <aside className="dbm-panel dbm-job-inspector" aria-label="Selected job stage inspector">
          <header className="dbm-panel-head">
            <div>
              <span className="dbm-eyebrow">STAGE FUNNEL INSPECTOR // {selectedJob.id.toUpperCase()}</span>
              <h3>{selectedJob.name}</h3>
            </div>
            <span className={`dbm-pill is-${selectedJob.status}`}>{selectedJob.status.toUpperCase()}</span>
          </header>

          {/* 4-Step Pipeline Stepper */}
          <ol className="dbm-stage-stepper" aria-label="Job execution stages">
            {STAGES.map((stage, idx) => {
              const currentIdx = STAGES.indexOf(selectedJob.currentStage);
              const state = idx < currentIdx ? 'done' : idx === currentIdx ? 'current' : 'upcoming';
              return (
                <li key={stage} className={`is-${state}`}>
                  <span>0{idx + 1}</span>
                  <strong>{stage}</strong>
                </li>
              );
            })}
          </ol>

          <dl className="dbm-dossier-facts">
            <div>
              <dt>Platform / Workload</dt>
              <dd>{selectedJob.site} · {selectedJob.type}</dd>
            </div>
            <div>
              <dt>Assigned Worker</dt>
              <dd><code>{selectedJob.workerId}</code></dd>
            </div>
            <div>
              <dt>Completion Ratio</dt>
              <dd><strong>{selectedPct}%</strong> ({selectedJob.completedTasks.toLocaleString()} / {selectedJob.totalTasks.toLocaleString()})</dd>
            </div>
            <div>
              <dt>Extraction Velocity</dt>
              <dd><strong>{selectedJob.itemsPerSec} items/s</strong> · {selectedJob.writeMbPerSec} MB/s</dd>
            </div>
            <div>
              <dt>Estimated Runway</dt>
              <dd>{selectedJob.etaMinutes > 0 ? `~${selectedJob.etaMinutes} minutes remaining` : 'Halted / Queued'}</dd>
            </div>
            <div>
              <dt>Failed Tasks</dt>
              <dd className={selectedJob.failedTasks > 0 ? 'is-danger-text' : ''}>{selectedJob.failedTasks} tasks</dd>
            </div>
          </dl>

          <div className="dbm-dossier-actions">
            {selectedJob.status === 'failed' ? (
              <button type="button" className="dbm-primary-btn" onClick={() => model.retryFailedJob(selectedJob.id)}>
                ↻ Requeue {selectedJob.failedTasks} Failed Tasks
              </button>
            ) : (
              <button type="button" className="dbm-primary-btn" onClick={() => model.toggleJobPause(selectedJob.id)}>
                {selectedJob.status === 'running' ? '⏸ Pause Job Execution' : '▶ Resume Job Execution'}
              </button>
            )}
          </div>
        </aside>
      </div>
    </section>
  );
}
