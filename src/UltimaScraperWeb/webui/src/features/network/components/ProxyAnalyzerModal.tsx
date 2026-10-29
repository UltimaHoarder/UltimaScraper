import type {
  AnalyzerErrorDetail,
  AnalyzerTab,
  GeolocationData,
  NetworkProxy,
  ProxyAnalyzerResponse,
  ProxyAnalyzerResult,
} from '../../../api/types/network';
import { getErrorCount, getErrorDetails, getGroupedAnalyzerResults } from '../lib/networkUtils';

interface ProxyAnalyzerModalProps {
  isOpen: boolean;
  proxy: NetworkProxy | null;
  tab: AnalyzerTab;
  analyzerData: ProxyAnalyzerResponse | null | undefined;
  analyzerError: string | null;
  isAnalyzing: boolean;
  progress: string;
  requestCount: number;
  useLiveCdn: boolean;
  geoLoading: boolean;
  geoError: string | null;
  onClose: () => void;
  onTabChange: (tab: AnalyzerTab) => void;
  onRequestCountChange: (value: number) => void;
  onUseLiveCdnChange: (value: boolean) => void;
  onFetchGeolocation: () => void;
  onStopAnalysis: () => void;
  onStartAnalysis: () => void;
  onApplyOptimalSettings: (applyToGroup?: boolean) => void;
  applySettingsPending: boolean;
  onShowErrorDetail: (detail: AnalyzerErrorDetail) => void;
}

const RUN_PRESETS = [
  { label: 'Quick', requests: 128, hint: 'Fast signal' },
  { label: 'Balanced', requests: 256, hint: 'Recommended' },
  { label: 'Deep', requests: 512, hint: 'High confidence' },
];

function successRate(result: ProxyAnalyzerResult) {
  return result.requests > 0 ? result.successes / result.requests : 0;
}

function findRecommended(
  analyzerData: ProxyAnalyzerResponse | null | undefined,
): ProxyAnalyzerResult | undefined {
  return analyzerData?.results.find(
    (result) =>
      result.concurrency === analyzerData.recommended_concurrency &&
      result.max_connections === analyzerData.recommended_connections,
  );
}

function AnalyzerOverview({
  proxy,
  analyzerData,
  isAnalyzing,
  onApply,
  onApplyToGroup,
  applyPending,
}: {
  proxy: NetworkProxy;
  analyzerData: ProxyAnalyzerResponse | null | undefined;
  isAnalyzing: boolean;
  onApply: () => void;
  onApplyToGroup?: () => void;
  applyPending: boolean;
}) {
  const recommended = findRecommended(analyzerData);
  const testedConfigurations = analyzerData?.results.length ?? 0;

  if (!recommended && !isAnalyzing && testedConfigurations === 0) {
    return (
      <div className="route-lab-empty">
        <div className="route-lab-empty__mark" aria-hidden="true">⌁</div>
        <span className="network-kicker">Ready to profile</span>
        <h3>Find this route&apos;s safe operating point</h3>
        <p>
          The analyzer ramps concurrent requests, checks connection-pool sizes, and stops when
          throughput gains no longer justify latency or failures.
        </p>
        <div className="route-lab-empty__steps">
          <span><strong>01</strong> Warm up route</span>
          <span><strong>02</strong> Ramp load</span>
          <span><strong>03</strong> Validate winner</span>
        </div>
      </div>
    );
  }

  return (
    <div className="route-lab-overview">
      {recommended ? (
        <section className="route-lab-recommendation">
          <div>
            <span className="network-kicker">Recommended operating point</span>
            <div className="route-lab-recommendation__value">
              <strong>{recommended.concurrency}</strong>
              <span>concurrent requests</span>
            </div>
            <p>
              Use a {recommended.max_connections}-connection pool for the best stable throughput
              observed in this run.
            </p>
          </div>
          <div className="route-lab-recommendation__apply">
            <small>Current connection limit</small>
            <strong>{proxy.max_connections === -1 ? 'Uncapped' : proxy.max_connections}</strong>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginTop: '8px' }}>
              <button
                type="button"
                className="network-button network-button--primary"
                onClick={onApply}
                disabled={applyPending}
              >
                {applyPending ? 'Applying…' : 'Apply recommendation'}
              </button>
              {proxy.group ? (
                <button
                  type="button"
                  className="network-button network-button--secondary"
                  onClick={onApplyToGroup}
                  disabled={applyPending}
                  title={`Apply ${recommended.max_connections} connections and ${recommended.concurrency} concurrency to all proxies in group "${proxy.group}"`}
                >
                  {applyPending ? 'Applying…' : `Apply to Group ("${proxy.group}")`}
                </button>
              ) : null}
            </div>
            {proxy.group ? (
              <small className="network-muted" style={{ display: 'block', marginTop: '4px' }}>
                Group: <strong>{proxy.group}</strong> · Tunes capacity across all group members
              </small>
            ) : null}
          </div>
        </section>
      ) : (
        <section className="route-lab-running">
          <span className="route-lab-running__pulse" />
          <div>
            <span className="network-kicker">Analysis in progress</span>
            <h3>Searching for the saturation point</h3>
            <p>Results appear as each load level completes.</p>
          </div>
        </section>
      )}

      {recommended ? (
        <div className="route-lab-metrics">
          <div><span>Success</span><strong>{Math.round(successRate(recommended) * 100)}%</strong></div>
          <div><span>Throughput</span><strong>{recommended.throughput_mbps.toFixed(2)} <small>Mbps</small></strong></div>
          <div><span>P95 latency</span><strong>{Math.round(recommended.p95_latency_ms)} <small>ms</small></strong></div>
          <div><span>Jitter</span><strong>{Math.round(recommended.jitter_ms)} <small>ms</small></strong></div>
        </div>
      ) : null}

      <div className="route-lab-coverage">
        <div>
          <span>Configurations tested</span>
          <strong>{testedConfigurations}</strong>
        </div>
        <div className="route-lab-coverage__bar">
          <span style={{ width: `${Math.min(100, testedConfigurations * 8)}%` }} />
        </div>
        <small>{isAnalyzing ? 'Run is still collecting evidence' : 'Run complete'}</small>
      </div>
    </div>
  );
}

function AnalyzerRuns({
  analyzerData,
  onShowErrorDetail,
}: {
  analyzerData: ProxyAnalyzerResponse | null | undefined;
  onShowErrorDetail: (detail: AnalyzerErrorDetail) => void;
}) {
  const grouped = getGroupedAnalyzerResults(analyzerData?.results ?? []);
  if (grouped.length === 0) {
    return <div className="route-lab-no-data">No completed load levels yet.</div>;
  }

  return (
    <div className="route-lab-table-wrap">
      <table className="route-lab-table">
        <thead>
          <tr>
            <th>Load</th>
            <th>Pool</th>
            <th>Success</th>
            <th>Throughput</th>
            <th>P95</th>
            <th>Jitter</th>
            <th>Errors</th>
          </tr>
        </thead>
        <tbody>
          {grouped.map(({ concurrency, bestResult }) => {
            const recommended =
              concurrency === analyzerData?.recommended_concurrency &&
              bestResult.max_connections === analyzerData.recommended_connections;
            const errors =
              getErrorCount(bestResult.head_status_counts) +
              getErrorCount(bestResult.download_status_counts);
            return (
              <tr key={concurrency} className={recommended ? 'is-recommended' : ''}>
                <td><strong>{recommended ? '★ ' : ''}{concurrency}×</strong></td>
                <td>{bestResult.max_connections}</td>
                <td><span className={`route-lab-rate ${successRate(bestResult) >= 0.95 ? 'is-good' : 'is-poor'}`}>{Math.round(successRate(bestResult) * 100)}%</span></td>
                <td>{bestResult.throughput_mbps.toFixed(2)} Mbps</td>
                <td>{Math.round(bestResult.p95_latency_ms)} ms</td>
                <td>{Math.round(bestResult.jitter_ms)} ms</td>
                <td>
                  {errors > 0 ? (
                    <button
                      type="button"
                      className="route-lab-error-link"
                      onClick={() => onShowErrorDetail({
                        endpoint: `${concurrency}× load`,
                        errors: {
                          ...getErrorDetails(bestResult.head_status_counts),
                          ...getErrorDetails(bestResult.download_status_counts),
                        },
                      })}
                    >
                      {errors} view
                    </button>
                  ) : '—'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="route-lab-table-note">Best connection pool shown for each concurrency level.</p>
    </div>
  );
}

function RouteDetails({
  geolocation,
  loading,
  error,
  onRefresh,
}: {
  geolocation?: GeolocationData | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}) {
  const available = geolocation && geolocation.success !== false;
  const rows = [
    ['Public IP', geolocation?.ip],
    ['Location', [geolocation?.city, geolocation?.region, geolocation?.country].filter(Boolean).join(', ')],
    ['Provider', geolocation?.connection?.isp],
    ['Organization', geolocation?.connection?.org],
    ['ASN', geolocation?.connection?.asn ? `AS${geolocation.connection.asn}` : undefined],
    ['Timezone', geolocation?.timezone?.id],
  ];

  return (
    <div className="route-lab-route-details">
      <div className="route-lab-detail-head">
        <div><span className="network-kicker">Observed exit</span><h3>Route identity</h3></div>
        <button type="button" className="network-button" onClick={onRefresh} disabled={loading}>
          {loading ? 'Resolving…' : available ? 'Refresh identity' : 'Resolve identity'}
        </button>
      </div>
      {error ? <div className="route-lab-error">{error}</div> : null}
      {available ? (
        <dl className="route-lab-detail-grid">
          {rows.filter(([, value]) => value).map(([label, value]) => (
            <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
          ))}
        </dl>
      ) : (
        <div className="route-lab-no-data">Resolve this route to see its public IP, region, provider, and timezone.</div>
      )}
    </div>
  );
}

export function ProxyAnalyzerModal({
  isOpen,
  proxy,
  tab,
  analyzerData,
  analyzerError,
  isAnalyzing,
  progress,
  requestCount,
  useLiveCdn,
  geoLoading,
  geoError,
  onClose,
  onTabChange,
  onRequestCountChange,
  onUseLiveCdnChange,
  onFetchGeolocation,
  onStopAnalysis,
  onStartAnalysis,
  onApplyOptimalSettings,
  applySettingsPending,
  onShowErrorDetail,
}: ProxyAnalyzerModalProps) {
  if (!isOpen || !proxy) return null;
  const activeTab = tab === 'results' || tab === 'geolocation' ? tab : 'settings';
  const routeName = proxy.id === 'direct' ? 'Direct connection' : proxy.url;

  return (
    <div className="modal-overlay route-lab-overlay" role="presentation">
      <section className="route-lab" role="dialog" aria-modal="true" aria-labelledby="route-lab-title">
        <header className="route-lab__header">
          <div>
            <span className="network-kicker">Network diagnostics</span>
            <h2 id="route-lab-title">Route analyzer</h2>
            <p>{routeName}</p>
          </div>
          <div className="route-lab__header-state">
            <span className={`network-status-dot ${isAnalyzing ? 'network-status-dot--testing' : 'network-status-dot--ready'}`} />
            {isAnalyzing ? 'Testing' : analyzerData?.results.length ? 'Results ready' : 'Ready'}
          </div>
          <button type="button" className="route-lab__close" onClick={onClose} aria-label="Close analyzer">×</button>
        </header>

        <div className="route-lab__body">
          <aside className="route-lab__setup">
            <div>
              <span className="network-kicker">Test depth</span>
              <div className="route-lab-presets">
                {RUN_PRESETS.map((preset) => (
                  <button
                    type="button"
                    key={preset.requests}
                    className={requestCount === preset.requests ? 'is-selected' : ''}
                    onClick={() => onRequestCountChange(preset.requests)}
                    disabled={isAnalyzing}
                  >
                    <strong>{preset.label}</strong>
                    <span>{preset.requests} requests</span>
                    <small>{preset.hint}</small>
                  </button>
                ))}
              </div>
            </div>

            <label className="route-lab-toggle">
              <input
                type="checkbox"
                checked={useLiveCdn}
                onChange={(event) => onUseLiveCdnChange(event.target.checked)}
                disabled={isAnalyzing}
              />
              <span className="route-lab-toggle__control" />
              <span><strong>Live CDN workload</strong><small>Use real media delivery paths</small></span>
            </label>

            <div className="route-lab-plan">
              <span>Adaptive plan</span>
              <p>Starts at 32×, probes both directions, then follows the stronger result until performance rolls over.</p>
            </div>

            {isAnalyzing ? (
              <button type="button" className="network-button network-button--danger route-lab-run" onClick={onStopAnalysis}>Stop analysis</button>
            ) : (
              <button type="button" className="network-button network-button--primary route-lab-run" onClick={onStartAnalysis}>
                {analyzerData?.results.length ? 'Run again' : 'Start analysis'}
              </button>
            )}
          </aside>

          <main className="route-lab__main">
            <nav className="route-lab-tabs" aria-label="Analyzer views">
              <button type="button" className={activeTab === 'settings' ? 'is-active' : ''} onClick={() => onTabChange('settings')}>Overview</button>
              <button type="button" className={activeTab === 'results' ? 'is-active' : ''} onClick={() => onTabChange('results')}>Load curve <span>{analyzerData?.results.length ?? 0}</span></button>
              <button type="button" className={activeTab === 'geolocation' ? 'is-active' : ''} onClick={() => onTabChange('geolocation')}>Route identity</button>
            </nav>

            {progress ? (
              <div className="route-lab-progress"><span className={isAnalyzing ? 'is-moving' : ''} />{progress}</div>
            ) : null}
            {analyzerError ? <div className="route-lab-error">{analyzerError}</div> : null}

            <div className="route-lab__content">
              {activeTab === 'settings' ? (
                <AnalyzerOverview
                  proxy={proxy}
                  analyzerData={analyzerData}
                  isAnalyzing={isAnalyzing}
                  onApply={() => onApplyOptimalSettings(false)}
                  onApplyToGroup={() => onApplyOptimalSettings(true)}
                  applyPending={applySettingsPending}
                />
              ) : null}
              {activeTab === 'results' ? <AnalyzerRuns analyzerData={analyzerData} onShowErrorDetail={onShowErrorDetail} /> : null}
              {activeTab === 'geolocation' ? <RouteDetails geolocation={proxy.geolocation} loading={geoLoading} error={geoError} onRefresh={onFetchGeolocation} /> : null}
            </div>
          </main>
        </div>
      </section>
    </div>
  );
}
