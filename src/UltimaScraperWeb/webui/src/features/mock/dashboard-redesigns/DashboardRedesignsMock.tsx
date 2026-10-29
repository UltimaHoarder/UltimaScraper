import { useSearchParams } from 'react-router-dom';
import { useDashboardMockModel, type DashboardTimeRange, type DashboardScenarioId } from './dashboardMockModel';
import { PulseCommandConcept } from './PulseCommandConcept';
import { PipelineTopologyConcept } from './PipelineTopologyConcept';
import { IncidentRunbookConcept } from './IncidentRunbookConcept';
import { FleetMatrixConcept } from './FleetMatrixConcept';
import { WorkloadRunwayConcept } from './WorkloadRunwayConcept';
import './DashboardRedesignsMock.css';

export const DASHBOARD_CONCEPTS = [
  {
    id: 'command',
    name: 'Pulse Command Deck',
    note: 'High-density operational cockpit uniting 6 live KPI sparklines, dual-axis scraping/I/O velocity, active jobs, worker unit array, proxy fabric, and correlated events.',
  },
  {
    id: 'topology',
    name: 'Acquisition Pipeline Schematic',
    note: 'End-to-end interactive node graph tracing assets from the Redis Claim Broker through Compute Workers and Geo-Proxy Pools into Tiered Storage Spillways.',
  },
  {
    id: 'triage',
    name: 'Incident & Triage Runbook',
    note: 'Reliability and exception-first command center highlighting active subsystem warnings, automated root-cause diagnosis, and 1-click runbook remediation.',
  },
  {
    id: 'fleet',
    name: 'Fleet & Proxy Matrix',
    note: 'Split-pane infrastructure workbench pairing a dense multi-region worker and proxy capacity matrix with a live Worker Unit Dossier inspector.',
  },
  {
    id: 'runway',
    name: 'Workload & Queue Runway',
    note: 'Execution-focused batch controller featuring live task completion bars, ETA runway forecasts, and a 4-stage pipeline funnel inspector.',
  },
] as const;

export type DashboardConceptId = typeof DASHBOARD_CONCEPTS[number]['id'];

const TIME_RANGES: DashboardTimeRange[] = ['15 min', '1 hour', '24 hours'];
const SCENARIOS: Array<{ id: DashboardScenarioId; label: string }> = [
  { id: 'nominal', label: 'Nominal Fleet' },
  { id: 'surge', label: 'MPS Surge' },
  { id: 'degraded', label: 'Degraded Incident' },
];

export function DashboardRedesignsMock() {
  const model = useDashboardMockModel();
  const [params, setParams] = useSearchParams();

  const requestedConcept = params.get('concept') as DashboardConceptId | null;
  const activeConcept =
    DASHBOARD_CONCEPTS.find((c) => c.id === requestedConcept) ?? DASHBOARD_CONCEPTS[0];

  const selectConcept = (id: string) => {
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.set('category', 'dashboard');
      next.set('concept', id);
      return next;
    });
    window.scrollTo({ top: 0, behavior: 'instant' });
  };

  return (
    <div className="dbm-lab" data-testid="dashboard-redesigns-mock">
      {/* Top Concept Switcher Navigation */}
      <div className="dbm-lab-controls">
        <nav className="dbm-concepts" aria-label="Dashboard design concepts">
          {DASHBOARD_CONCEPTS.map((concept, index) => (
            <button
              type="button"
              key={concept.id}
              aria-pressed={activeConcept.id === concept.id}
              onClick={() => selectConcept(concept.id)}
            >
              <span>0{index + 1}</span>
              {concept.name}
            </button>
          ))}
        </nav>

        <label className="dbm-concept-select">
          <span>Design</span>
          <select
            aria-label="Dashboard design concept"
            value={activeConcept.id}
            onChange={(e) => selectConcept(e.target.value)}
          >
            {DASHBOARD_CONCEPTS.map((concept, index) => (
              <option key={concept.id} value={concept.id}>
                0{index + 1} · {concept.name}
              </option>
            ))}
          </select>
        </label>

        <div className="dbm-lab-right-controls">
          <button
            type="button"
            className={`dbm-stream-btn ${model.liveStream ? 'is-active' : ''}`}
            aria-pressed={model.liveStream}
            onClick={() => model.setLiveStream((v) => !v)}
          >
            <i className={`dbm-status-dot ${model.liveStream ? 'is-info' : 'is-offline'}`} />
            {model.liveStream ? 'Live Telemetry' : 'Stream Paused'}
          </button>

          <button type="button" className="dbm-quiet-btn" onClick={model.reset}>
            Reset preview
          </button>
        </div>
      </div>

      {/* Active Concept Pitch Note */}
      <p className="dbm-concept-note">{activeConcept.note}</p>

      {/* Scenario & Time Window Toolbar */}
      <div className="dbm-toolbar" role="toolbar" aria-label="Dashboard simulation controls">
        <div className="dbm-toolbar-group" role="group" aria-label="Operational scenario preset">
          <span className="dbm-toolbar-label">Scenario:</span>
          {SCENARIOS.map((item) => (
            <button
              type="button"
              key={item.id}
              className={`dbm-scenario-btn ${model.scenario === item.id ? 'is-active' : ''}`}
              aria-pressed={model.scenario === item.id}
              onClick={() => model.applyScenario(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="dbm-toolbar-group" role="group" aria-label="Dashboard time range">
          <span className="dbm-toolbar-label">Window:</span>
          {TIME_RANGES.map((r) => (
            <button
              type="button"
              key={r}
              className={`dbm-range-btn ${model.range === r ? 'is-active' : ''}`}
              aria-pressed={model.range === r}
              onClick={() => model.setRange(r)}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {/* Interactive Feedback Toast */}
      {model.notice && (
        <div className="dbm-notice" role="status" aria-live="polite">
          <span>⚡ {model.notice}</span>
          <small>Sample preview state</small>
        </div>
      )}

      {/* Stage Workspace Header */}
      <header className="dbm-workspace-header">
        <div>
          <span className="dbm-eyebrow">US-CT // 02 SYSTEM TELEMETRY &amp; OPERATIONS</span>
          <h2>{activeConcept.name}</h2>
        </div>
        <div className="dbm-workspace-status">
          <span className={`dbm-pill ${model.kpis.unresolvedIncidents > 0 ? 'is-queued' : 'is-running'}`}>
            {model.kpis.unresolvedIncidents > 0
              ? `${model.kpis.unresolvedIncidents} ACTIVE ALERTS`
              : 'SYSTEMS NOMINAL'}
          </span>
          <code>NODE: backend_local</code>
        </div>
      </header>

      {/* Render Active Concept */}
      <div className="dbm-stage">
        {activeConcept.id === 'command' && <PulseCommandConcept model={model} />}
        {activeConcept.id === 'topology' && <PipelineTopologyConcept model={model} />}
        {activeConcept.id === 'triage' && <IncidentRunbookConcept model={model} />}
        {activeConcept.id === 'fleet' && <FleetMatrixConcept model={model} />}
        {activeConcept.id === 'runway' && <WorkloadRunwayConcept model={model} />}
      </div>
    </div>
  );
}
