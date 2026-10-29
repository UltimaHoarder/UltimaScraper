import type { DashboardMockModel } from './dashboardMockModel';

export function IncidentRunbookConcept({ model }: { model: DashboardMockModel }) {
  const { incidents, kpis, filteredEvents, eventFilter, setEventFilter } = model;
  const activeIncidents = incidents.filter((i) => !i.resolved);

  return (
    <section className="dbm-concept dbm-incident-runbook" aria-label="Incident & Triage Runbook">
      {/* Top SLA & Alert Banner */}
      <div className="dbm-triage-banner">
        <div className="dbm-triage-score">
          <span>FLEET RELIABILITY SLA</span>
          <strong className={kpis.unresolvedIncidents > 0 ? 'is-warning' : 'is-accent'}>
            {kpis.unresolvedIncidents === 0 ? '99.98%' : `${kpis.successRate}%`}
          </strong>
          <small>{kpis.unresolvedIncidents} active runbook {kpis.unresolvedIncidents === 1 ? 'incident' : 'incidents'}</small>
        </div>
        <div className="dbm-triage-subsystems">
          <div className="dbm-sub-pill is-ok">
            <span>REDIS BROKER</span>
            <strong>NOMINAL (1.4ms)</strong>
          </div>
          <div className="dbm-sub-pill is-warn">
            <span>PROXY FABRIC</span>
            <strong>3 THROTTLED (429)</strong>
          </div>
          <div className={`dbm-sub-pill ${incidents.find((i) => i.id === 'inc-spillway')?.resolved ? 'is-ok' : 'is-warn'}`}>
            <span>STORAGE SPILLWAY</span>
            <strong>{incidents.find((i) => i.id === 'inc-spillway')?.resolved ? 'BALANCED' : 'OVERFLOW ACTIVE'}</strong>
          </div>
          <div className={`dbm-sub-pill ${incidents.find((i) => i.id === 'inc-transcode')?.resolved ? 'is-ok' : 'is-crit'}`}>
            <span>TRANSCODE FLEET</span>
            <strong>{incidents.find((i) => i.id === 'inc-transcode')?.resolved ? 'HEALTHY' : '1 NODE DEGRADED'}</strong>
          </div>
        </div>
      </div>

      <div className="dbm-triage-columns">
        {/* Left Column: Actionable Runbook Cards */}
        <article className="dbm-panel">
          <header className="dbm-panel-head">
            <div>
              <span className="dbm-eyebrow">AUTOMATED DIAGNOSTICS // RUNBOOK REMEDIATION</span>
              <h3>Active Subsystem Alerts</h3>
            </div>
            <span className="dbm-badge">{activeIncidents.length} unresolved</span>
          </header>

          <div className="dbm-runbook-list">
            {incidents.map((inc) => (
              <div key={inc.id} className={`dbm-runbook-card is-${inc.severity} ${inc.resolved ? 'is-resolved' : ''}`}>
                <div className="dbm-runbook-top">
                  <span className={`dbm-pill is-${inc.resolved ? 'running' : inc.severity === 'critical' ? 'failed' : 'queued'}`}>
                    {inc.resolved ? 'RESOLVED' : inc.severity.toUpperCase()}
                  </span>
                  <span className="dbm-eyebrow">{inc.subsystem}</span>
                </div>
                <h4>{inc.title}</h4>
                <p>{inc.diagnosis}</p>
                <div className="dbm-runbook-foot">
                  {inc.resolved ? (
                    <span className="dbm-resolved-tag">✓ Remediation verified in preview</span>
                  ) : (
                    <button
                      type="button"
                      className="dbm-primary-btn"
                      onClick={() => model.resolveIncident(inc.id)}
                    >
                      ⚡ {inc.remediationLabel}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </article>

        {/* Right Column: Live Correlated Diagnostic Stream */}
        <article className="dbm-panel">
          <header className="dbm-panel-head">
            <div>
              <span className="dbm-eyebrow">CORRELATED TELEMETRY TIMELINE</span>
              <h3>Audit &amp; Error Event Ledger</h3>
            </div>
            <div className="dbm-filter-pills" role="group" aria-label="Filter triage events">
              {(['all', 'critical', 'warning', 'info'] as const).map((sev) => (
                <button
                  type="button"
                  key={sev}
                  className={eventFilter === sev ? 'is-active' : ''}
                  onClick={() => setEventFilter(sev)}
                >
                  {sev}
                </button>
              ))}
            </div>
          </header>

          <div className="dbm-event-stream dbm-event-stream--tall">
            {filteredEvents.map((ev) => (
              <div key={ev.id} className={`dbm-event-item is-${ev.severity}`}>
                <time>{ev.timestamp}</time>
                <i className={`dbm-status-dot is-${ev.severity}`} />
                <div>
                  <div className="dbm-event-head-row">
                    <strong>{ev.title}</strong>
                    <code>{ev.category.toUpperCase()}</code>
                  </div>
                  <small>{ev.source} · {ev.detail}</small>
                </div>
              </div>
            ))}
          </div>
        </article>
      </div>
    </section>
  );
}
