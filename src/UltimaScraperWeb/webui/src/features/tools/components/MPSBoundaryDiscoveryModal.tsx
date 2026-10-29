import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { discoverBounds, getDiscoverBoundsStreamUrl } from '../../../api/mps';
import type {
  MPSBoundaryDiscoveryRequest,
  MPSBoundaryDiscoveryResponse,
  MPSProbeObservation,
} from '../../../api/types/mps';
import { parseOptionalInt } from '../lib/toolsUtils';
import './MPSBoundaryDiscoveryModal.css';

export interface MPSBoundaryDiscoveryModalProps {
  isOpen: boolean;
  site: string;
  defaultStartingId?: number | null;
  onClose: () => void;
  onApply: (startId: number, endId: number, result: MPSBoundaryDiscoveryResponse) => void;
}

interface PhaseDefinition {
  id: string;
  title: string;
  description: string;
}

const PHASES: PhaseDefinition[] = [
  {
    id: 'exponential',
    title: 'Exponential Probing',
    description: 'Searches brackets from highest known ID',
  },
  {
    id: 'refinement',
    title: 'Bisection Refinement',
    description: 'Pinpoints boundary ceiling via bisection',
  },
  {
    id: 'sampling',
    title: 'Population Sampling',
    description: 'Estimates density & Wilson 95% confidence',
  },
];

export function MPSBoundaryDiscoveryModal({
  isOpen,
  site,
  defaultStartingId,
  onClose,
  onApply,
}: MPSBoundaryDiscoveryModalProps) {
  const [startingIdInput, setStartingIdInput] = useState<string>(() =>
    defaultStartingId ? String(defaultStartingId) : '',
  );
  const [maxProbesInput, setMaxProbesInput] = useState('50');

  const [status, setStatus] = useState<'idle' | 'running' | 'completed' | 'error'>('idle');
  const [currentPhase, setCurrentPhase] = useState<string | null>(null);
  const [phaseMessage, setPhaseMessage] = useState<string | null>(null);
  const [probes, setProbes] = useState<MPSProbeObservation[]>([]);
  const [totalProbesUsed, setTotalProbesUsed] = useState(0);
  const [highestObservedId, setHighestObservedId] = useState<number | null>(null);
  const [result, setResult] = useState<MPSBoundaryDiscoveryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const activeEventSourceRef = useRef<EventSource | null>(null);
  const logEndRef = useRef<HTMLDivElement | null>(null);
  const tableWrapperRef = useRef<HTMLDivElement | null>(null);
  const userScrolledUpRef = useRef<boolean>(false);

  // Sync default starting ID when modal opens or prop changes if not running
  // (adjusted while rendering, not in an effect).
  const startingIdToSync = isOpen && status === 'idle' && defaultStartingId ? String(defaultStartingId) : null;
  const [syncedStartingId, setSyncedStartingId] = useState<string | null>(null);
  if (startingIdToSync !== syncedStartingId) {
    setSyncedStartingId(startingIdToSync);
    if (startingIdToSync !== null) setStartingIdInput(startingIdToSync);
  }

  // Clean up active streaming connection on unmount or close
  const cleanupStream = useCallback(() => {
    if (activeEventSourceRef.current) {
      activeEventSourceRef.current.close();
      activeEventSourceRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!isOpen) {
      cleanupStream();
    }
  }, [isOpen, cleanupStream]);

  // Track if user manually scrolled up so we don't fight their scroll position
  const handleTableScroll = useCallback(() => {
    const el = tableWrapperRef.current;
    if (!el) return;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    userScrolledUpRef.current = distanceToBottom > 45;
  }, []);

  // Auto-scroll table wrapper to keep the active 10 items in view without page jumping
  useEffect(() => {
    if (!userScrolledUpRef.current && tableWrapperRef.current) {
      tableWrapperRef.current.scrollTop = tableWrapperRef.current.scrollHeight;
    }
  }, [probes]);

  const validHitsCount = useMemo(() => {
    if (result) return result.valid_probes_count;
    return probes.filter((p) => p.is_valid).length;
  }, [probes, result]);

  const handleRunDiscovery = useCallback(async () => {
    cleanupStream();
    userScrolledUpRef.current = false;
    setStatus('running');
    setError(null);
    setProbes([]);
    setTotalProbesUsed(0);
    setHighestObservedId(null);
    setResult(null);
    setCurrentPhase('exponential');
    setPhaseMessage('Connecting to adaptive boundary discovery…');

    const minId =
      parseOptionalInt(startingIdInput) ??
      (defaultStartingId ? defaultStartingId : undefined);
    const maxProbes = parseOptionalInt(maxProbesInput) ?? 50;

    const request: MPSBoundaryDiscoveryRequest = {
      site,
      min_id: minId,
      max_probes: maxProbes,
    };

    let fallbackCalled = false;
    const runFallbackPost = async () => {
      if (fallbackCalled) return;
      fallbackCalled = true;
      cleanupStream();
      try {
        const data = await discoverBounds(request);
        setResult(data);
        if (data.observations && data.observations.length > 0) {
          setProbes(data.observations);
        }
        setTotalProbesUsed(data.total_probes_used);
        if (data.highest_observed_id != null) {
          setHighestObservedId(data.highest_observed_id);
        }
        setCurrentPhase(null);
        setPhaseMessage('Boundary discovery completed.');
        setStatus('completed');
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err);
        setError(message);
        setStatus('error');
        setPhaseMessage(`Boundary discovery failed: ${message}`);
      }
    };

    if (typeof EventSource !== 'undefined') {
      try {
        const streamUrl = getDiscoverBoundsStreamUrl(request);
        const eventSource = new EventSource(streamUrl);
        activeEventSourceRef.current = eventSource;

        eventSource.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            if (data.type === 'start') {
              setStatus('running');
              setPhaseMessage(
                `Probing ${data.site} starting from ID ${data.starting_id?.toLocaleString() ?? 1}…`,
              );
            } else if (data.type === 'phase') {
              setCurrentPhase(data.phase);
              setPhaseMessage(data.message);
            } else if (data.type === 'probe') {
              setProbes((prev) => [
                ...prev,
                {
                  user_id: data.user_id,
                  is_valid: data.is_valid,
                  phase: data.phase,
                  timestamp: Date.now(),
                },
              ]);
              setTotalProbesUsed(data.total_probes);
              if (data.highest_observed_id != null) {
                setHighestObservedId(data.highest_observed_id);
              }
            } else if (data.type === 'complete') {
              setResult(data.result);
              if (data.result.observations && data.result.observations.length > 0) {
                setProbes(data.result.observations);
              }
              setStatus('completed');
              setCurrentPhase(null);
              setPhaseMessage('Boundary discovery completed.');
              cleanupStream();
            } else if (data.type === 'error') {
              setError(data.message);
              setStatus('error');
              setPhaseMessage(`Boundary discovery failed: ${data.message}`);
              cleanupStream();
            }
          } catch (parseErr) {
            console.error('Failed parsing stream message:', parseErr);
          }
        };

        eventSource.onerror = () => {
          // If connection fails, seamlessly fallback to POST request
          void runFallbackPost();
        };
      } catch {
        void runFallbackPost();
      }
    } else {
      void runFallbackPost();
    }
  }, [
    cleanupStream,
    startingIdInput,
    maxProbesInput,
    site,
    defaultStartingId,
  ]);

  const handleStop = () => {
    cleanupStream();
    setStatus('idle');
    setPhaseMessage('Discovery paused by user.');
  };

  const handleApply = () => {
    if (!result) return;
    onApply(result.discovered_start_id, result.discovered_end_id, result);
    onClose();
  };

  if (!isOpen) {
    return null;
  }

  const budget = parseOptionalInt(maxProbesInput) ?? 50;

  return (
    <div
      className="mps-boundary-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="boundary-discovery-title"
      onClick={onClose}
    >
      <div className="mps-boundary-modal" onClick={(e) => e.stopPropagation()}>
        <header className="mps-boundary-header">
          <div className="mps-boundary-header-title">
            <h2 id="boundary-discovery-title">Discover User ID Boundaries: {site}</h2>
            <p>
              Adaptive sampling probes the site starting from our highest known ID to estimate active
              boundaries and total user population.
            </p>
          </div>
          <button
            type="button"
            className="mps-boundary-close-btn"
            aria-label="Close boundary discovery"
            onClick={onClose}
          >
            ×
          </button>
        </header>

        <div className="mps-boundary-body">
          {/* Controls Bar */}
          <div className="mps-boundary-config">
            <div className="mps-boundary-config-row">
              <label className="tools-field">
                <span>Starting ID</span>
                <input
                  type="number"
                  min={1}
                  value={startingIdInput}
                  disabled={status === 'running'}
                  onChange={(e) => setStartingIdInput(e.target.value)}
                  placeholder={defaultStartingId ? String(defaultStartingId) : '1'}
                  title="Starting ID for exponential discovery (defaults to highest known ID)"
                />
              </label>

              <label className="tools-field">
                <span>Max Probes</span>
                <input
                  type="number"
                  min={5}
                  max={500}
                  value={maxProbesInput}
                  disabled={status === 'running'}
                  onChange={(e) => setMaxProbesInput(e.target.value)}
                />
              </label>

              <div className="mps-boundary-config-actions">
                {status === 'running' ? (
                  <button
                    type="button"
                    className="tools-btn tools-btn-secondary"
                    onClick={handleStop}
                  >
                    Stop
                  </button>
                ) : (
                  <button
                    type="button"
                    className="tools-btn tools-btn-primary"
                    onClick={() => void handleRunDiscovery()}
                  >
                    {result ? 'Run Again' : 'Start Discovery'}
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Phase Stepper */}
          <div className="mps-boundary-phases" aria-label="Discovery phases">
            {PHASES.map((phase, idx) => {
              const isDone =
                status === 'completed' ||
                (currentPhase === 'refinement' && phase.id === 'exponential') ||
                (currentPhase === 'sampling' &&
                  (phase.id === 'exponential' || phase.id === 'refinement'));
              const isActive = status === 'running' && currentPhase === phase.id;

              return (
                <div
                  key={phase.id}
                  className={`mps-phase-step ${isActive ? 'active' : ''} ${isDone ? 'done' : ''}`}
                >
                  <div className="mps-phase-step-head">
                    <span className="mps-phase-icon">
                      {isDone ? '✓' : isActive ? '●' : idx + 1}
                    </span>
                    <span>{phase.title}</span>
                  </div>
                  <span className="mps-phase-desc">{phase.description}</span>
                </div>
              );
            })}
          </div>

          {/* Metrics Tiles */}
          <div className="mps-boundary-metrics" aria-label="Discovery metrics">
            <div className="mps-boundary-metric-card">
              <span className="mps-boundary-metric-label">Probes Used</span>
              <strong className="mps-boundary-metric-value accent">
                {totalProbesUsed} / {budget}
              </strong>
            </div>

            <div className="mps-boundary-metric-card">
              <span className="mps-boundary-metric-label">Valid Hits</span>
              <strong className="mps-boundary-metric-value success">
                {validHitsCount}
                {totalProbesUsed > 0 && (
                  <small style={{ fontSize: '0.72rem', color: 'var(--mps-dim)', marginLeft: '4px' }}>
                    ({Math.round((validHitsCount / totalProbesUsed) * 100)}%)
                  </small>
                )}
              </strong>
            </div>

            <div className="mps-boundary-metric-card">
              <span className="mps-boundary-metric-label">Highest Observed ID</span>
              <strong className="mps-boundary-metric-value">
                {highestObservedId !== null ? highestObservedId.toLocaleString() : '—'}
              </strong>
            </div>

            <div className="mps-boundary-metric-card">
              <span className="mps-boundary-metric-label">Status</span>
              <strong
                className="mps-boundary-metric-value"
                style={{ fontSize: '0.85rem', textTransform: 'capitalize' }}
              >
                {status}
              </strong>
            </div>
          </div>

          {/* Real-time Probe Observation Log Feed */}
          <div className="mps-boundary-feed-section">
            <div className="mps-boundary-feed-title-row">
              <strong>Real-Time Probe Activity ({probes.length})</strong>
              {phaseMessage && <span>{phaseMessage}</span>}
            </div>

            <div
              className="mps-boundary-log-table-wrapper"
              ref={tableWrapperRef}
              onScroll={handleTableScroll}
            >
              {probes.length === 0 ? (
                <div className="mps-boundary-empty-feed">
                  {status === 'running'
                    ? 'Probing ID space… incoming observations will appear here.'
                    : 'Click "Start Discovery" to begin probing.'}
                </div>
              ) : (
                <table className="mps-boundary-log-table">
                  <thead>
                    <tr>
                      <th style={{ width: '45px' }}>#</th>
                      <th>User ID</th>
                      <th>Phase</th>
                      <th>Lookup Result</th>
                    </tr>
                  </thead>
                  <tbody>
                    {probes.map((probe, index) => {
                      const isLatest = index === probes.length - 1;
                      const isActive = status === 'running' && isLatest;
                      return (
                        <tr
                          key={`${probe.user_id}-${index}`}
                          className={isActive ? 'mps-probe-row-active' : undefined}
                        >
                          <td>
                            {isActive ? (
                              <span className="mps-probe-pulse-dot" title="Active probe" />
                            ) : (
                              index + 1
                            )}
                          </td>
                          <td>
                            <strong>{probe.user_id.toLocaleString()}</strong>
                            {isActive && <span className="mps-probe-active-tag">Active</span>}
                          </td>
                          <td>
                            <span className="mps-phase-tag">{probe.phase}</span>
                          </td>
                          <td>
                            <span
                              className={`mps-probe-badge ${probe.is_valid ? 'valid' : 'invalid'}`}
                            >
                              {probe.is_valid ? 'Valid User ✓' : 'Not Found ✗'}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
              <div ref={logEndRef} />
            </div>
          </div>

          {/* Results Summary Card */}
          {result && (
            <div className="mps-boundary-result-card">
              <div className="mps-boundary-result-head">
                <span className="mps-boundary-result-badge">
                  ✓ Boundary Discovery Complete
                </span>
                <span style={{ fontSize: '0.78rem', color: 'var(--mps-dim)' }}>
                  Used {result.total_probes_used} probes ({result.valid_probes_count} valid hits)
                </span>
              </div>

              <div className="mps-boundary-result-grid">
                <div className="mps-boundary-result-item">
                  <span>Discovered ID Range</span>
                  <strong>
                    {result.discovered_start_id.toLocaleString()} –{' '}
                    {result.discovered_end_id.toLocaleString()}
                  </strong>
                  <small>
                    Span: {(result.discovered_end_id - result.discovered_start_id + 1).toLocaleString()} IDs
                  </small>
                </div>

                <div className="mps-boundary-result-item">
                  <span>Estimated Total Users</span>
                  <strong>~{result.estimated_total_users.toLocaleString()}</strong>
                  <small>
                    95% CI: [{result.population_confidence_interval[0].toLocaleString()} –{' '}
                    {result.population_confidence_interval[1].toLocaleString()}]
                  </small>
                </div>

                <div className="mps-boundary-result-item">
                  <span>Estimated Population Density</span>
                  <strong>{(result.estimated_density * 100).toFixed(1)}%</strong>
                  <small>
                    ±{(result.density_margin_of_error * 100).toFixed(1)}% margin of error
                  </small>
                </div>

                <div className="mps-boundary-result-item">
                  <span>Highest ID Confidence (95%)</span>
                  <strong>
                    [{result.highest_id_confidence_interval[0].toLocaleString()} –{' '}
                    {result.highest_id_confidence_interval[1].toLocaleString()}]
                  </strong>
                  <small>
                    Observed max: {result.highest_observed_id?.toLocaleString() ?? '—'}
                  </small>
                </div>
              </div>

              {result.warnings.length > 0 && (
                <div style={{ marginTop: '8px' }}>
                  {result.warnings.map((w) => (
                    <div key={w} className="mps-map-warning">
                      {w}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Error Alert */}
          {error && <div className="tools-alert error">{error}</div>}
        </div>

        <footer className="mps-boundary-footer">
          <div className="mps-boundary-footer-status">
            {status === 'running' && (
              <>
                <span className="mps-analysis-spinner" aria-hidden="true" />
                <span>Running discovery…</span>
              </>
            )}
            {status === 'completed' && result && (
              <span>
                Discovered boundaries: {result.discovered_start_id.toLocaleString()} –{' '}
                {result.discovered_end_id.toLocaleString()}
              </span>
            )}
            {status === 'idle' && <span>Ready to probe. Click &quot;Start Discovery&quot; to begin.</span>}
          </div>

          <div className="mps-boundary-footer-actions">
            <button
              type="button"
              className="tools-btn tools-btn-secondary"
              onClick={onClose}
            >
              Close
            </button>
            {result && (
              <button
                type="button"
                className="tools-btn tools-btn-primary"
                onClick={handleApply}
              >
                Apply to MPS ({result.discovered_start_id.toLocaleString()} –{' '}
                {result.discovered_end_id.toLocaleString()})
              </button>
            )}
          </div>
        </footer>
      </div>
    </div>
  );
}
