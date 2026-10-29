import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { analyzeMps, createMpsJob, getSiteBounds, previewMpsProxies } from '../../../api/mps';
import type {
  MPSAnalyzeRequest,
  MPSAnalyzeResponse,
  MPSBoundaryDiscoveryResponse,
  MPSCreateJobResponse,
  MPSProxyMode,
  MPSProxyPreviewResponse,
} from '../../../api/types/mps';
import { parseOptionalFloat, parseOptionalInt, parseOptionalString } from '../lib/toolsUtils';
import { ToastPortal } from '../../../shared/ui/ToastPortal';
import { MPSIdSpaceMap } from './MPSIdSpaceMap';
import { MPSBoundaryDiscoveryModal } from './MPSBoundaryDiscoveryModal';
import { JobDetailsModal } from '../../jobs/components/JobDetailsModal';
import { calculateAdaptiveBatchSize } from '../lib/mpsAdaptiveBatch';
import './MPSTool.css';

interface AnalyzeVariables {
  candidateOffset?: number;
  batchSize?: number | null;
  bounded?: boolean;
  request?: MPSAnalyzeRequest;
  requestKey?: string;
  requestId?: number;
}

interface CreateVariables {
  candidateOffset?: number;
  maxProfiles?: number | null;
  maxRouteHops?: number;
  conclusiveMissThreshold?: number;
}

type MPSRecheckUnit = 'hours' | 'days' | 'weeks';

const RECHECK_UNIT_HOURS: Record<MPSRecheckUnit, number> = {
  hours: 1,
  days: 24,
  weeks: 24 * 7,
};
function parseRecheckHours(value: string, unit: MPSRecheckUnit): number | null {
  const amount = parseOptionalFloat(value);
  return amount === null ? null : amount * RECHECK_UNIT_HOURS[unit];
}

function formatRecheckWindow(value: string, unit: MPSRecheckUnit): string {
  const amount = parseOptionalFloat(value);
  if (amount === null) {
    return 'No cooldown: every selected previously checked profile is eligible.';
  }
  const singularUnit = unit.slice(0, -1);
  const displayUnit = amount === 1 ? singularUnit : unit;
  return `Profiles checked within the last ${amount.toLocaleString()} ${displayUnit} stay out of this run.`;
}

function formatCount(value: number | null | undefined): string {
  return Number(value ?? 0).toLocaleString();
}

function buildProxyWarnings(
  proxyPreview: MPSProxyPreviewResponse | undefined,
  selectedProfiles: number,
): string[] {
  if (!proxyPreview || selectedProfiles <= 0) {
    return [];
  }

  const warnings: string[] = [];
  if (proxyPreview.proxies_used === 0 && selectedProfiles >= 2_500) {
    warnings.push(
      `Only the direct connection is selected for ${formatCount(selectedProfiles)} queued profiles. Consider smaller batches or enabling proxies.`,
    );
  }

  return warnings;
}

function buildMpsSuccessNotice(result: MPSCreateJobResponse): string {
  if (['queued', 'materializing', 'finalizing'].includes(result.job.materialization_status ?? '')) {
    return `Job ${result.job.job_id} accepted. Materializing ${formatCount(result.selected_profiles)} profile tasks in the background. ${formatCount(result.remaining_candidate_count)} candidate(s) remain in this filtered set.`;
  }
  return `Job ${result.job.job_id} created with ${formatCount(result.selected_profiles)} profile tasks. ${formatCount(result.remaining_candidate_count)} candidate(s) remain in this filtered set.`;
}

export function MPSTool() {
  const queryClient = useQueryClient();

  const [site, setSite] = useState('OnlyFans');
  const [startIdInput, setStartIdInput] = useState('');
  const [endIdInput, setEndIdInput] = useState('');
  const [includeMissingIds, setIncludeMissingIds] = useState(true);
  const [includeInvalid, setIncludeInvalid] = useState(false);
  const [includeExistingUsers, setIncludeExistingUsers] = useState(false);
  const [recheckAgeInput, setRecheckAgeInput] = useState('7');
  const [recheckAgeUnit, setRecheckAgeUnit] = useState<MPSRecheckUnit>('days');

  const [routesOpen, setRoutesOpen] = useState(false);
  const [openedJob, setOpenedJob] = useState<MPSCreateJobResponse['job'] | null>(null);
  const routesDialog = useRef<HTMLDialogElement>(null);
  const latestRequestId = useRef(0);
  const activeRequestKey = useRef('');
  const autoTimer = useRef<number | undefined>(undefined);
  const [analysisRevision, setAnalysisRevision] = useState(0);
  const [analysis, setAnalysis] = useState<MPSAnalyzeResponse | null>(null);
  const [candidateOffset, setCandidateOffset] = useState(0);
  const [lastCreatedJob, setLastCreatedJob] = useState<MPSCreateJobResponse | null>(null);
  const [analyzingMode, setAnalyzingMode] = useState<'quick' | 'full' | null>(null);

  const [maxProfilesInput, setMaxProfilesInput] = useState('');
  const [isMaxProfilesOverridden, setIsMaxProfilesOverridden] = useState(false);
  const [proxyMode, setProxyMode] = useState<MPSProxyMode>('unassigned_only');
  const [includeDirectConnection, setIncludeDirectConnection] = useState(false);
  const [maxRouteHopsInput, setMaxRouteHopsInput] = useState('3');
  const [conclusiveMissThresholdInput, setConclusiveMissThresholdInput] = useState('3');
  const [customProxyUrlsInput, setCustomProxyUrlsInput] = useState('');
  const [jobNameInput, setJobNameInput] = useState('');

  const [notice, setNotice] = useState<{ type: 'success' | 'error'; text: string } | null>(
    null,
  );

  useEffect(() => {
    if (notice?.type !== 'success') return;
    const timer = window.setTimeout(() => setNotice(null), 8_000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const customProxyUrls = useMemo(
    () =>
      customProxyUrlsInput
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean),
    [customProxyUrlsInput],
  );

  const requestedBatchSize = parseOptionalInt(maxProfilesInput);
  const recheckAgeHours = parseRecheckHours(recheckAgeInput, recheckAgeUnit);
  const rawMaxRouteHops = parseOptionalInt(maxRouteHopsInput);
  const maxRouteHops =
    rawMaxRouteHops === null ? 3 : Math.max(1, Math.min(5, rawMaxRouteHops));
  const rawMissThreshold = parseOptionalInt(conclusiveMissThresholdInput);
  const conclusiveMissThreshold =
    rawMissThreshold === null ? 3 : Math.max(1, Math.min(5, rawMissThreshold));

  const proxyPreviewQuery = useQuery({
    queryKey: [
      'mps-proxy-preview',
      site,
      proxyMode,
      includeDirectConnection,
      customProxyUrls,
    ],
    queryFn: async () =>
      previewMpsProxies({
        site,
        use_proxies: proxyMode !== 'none',
        proxy_mode: proxyMode,
        proxy_urls: proxyMode === 'custom' ? customProxyUrls : null,
        include_direct_connection: includeDirectConnection,
      }),
    enabled: true,
    staleTime: 0,
    refetchOnWindowFocus: true,
  });

  const siteBoundsQuery = useQuery({
    queryKey: ['mps-site-bounds', site],
    queryFn: async () => getSiteBounds(site),
    staleTime: 30_000,
  });

  const routes = useMemo(() => {
    if (!proxyPreviewQuery.data) return 1;
    const count =
      proxyPreviewQuery.data.proxies_used +
      Number(proxyPreviewQuery.data.direct_connection_included);
    return Math.max(1, count);
  }, [proxyPreviewQuery.data]);

  const analysisScope = useMemo(() => ({
    site,
    start_id: parseOptionalInt(startIdInput),
    end_id: parseOptionalInt(endIdInput),
    ignore_missing_ids: !includeMissingIds,
    include_invalid: includeInvalid,
    invalid_last_checked_older_than_hours: includeInvalid ? recheckAgeHours : null,
    include_existing_users: includeExistingUsers,
    existing_last_checked_older_than_hours: includeExistingUsers ? recheckAgeHours : null,
    missing_preview_limit: 1,
    range_preview_limit: 1000,
    density_resolution: 72,
    routes,
  }), [site, startIdInput, endIdInput, includeMissingIds, includeInvalid, includeExistingUsers, recheckAgeHours, routes]);
  const requestKey = JSON.stringify([analysisScope, analysisRevision]);
  useEffect(() => { activeRequestKey.current = requestKey; }, [requestKey]);

  const analyzeMutation = useMutation({
    mutationFn: async (variables?: AnalyzeVariables) =>
      analyzeMps(variables?.request ?? {
        ...analysisScope,
        candidate_offset: variables?.candidateOffset ?? candidateOffset,
        batch_size: variables?.batchSize ?? requestedBatchSize,
        bounded: variables?.bounded ?? false,
      }),
    onSuccess: (data, variables) => {
      if (variables?.requestKey !== activeRequestKey.current || variables?.requestId !== latestRequestId.current) return;
      setAnalyzingMode(null);
      setAnalysis(data);
      const adaptive = calculateAdaptiveBatchSize(data, {
        includeMissingIds,
        routes,
      });
      if (!isMaxProfilesOverridden && adaptive && adaptive.value > 0) {
        setMaxProfilesInput(adaptive.value.toString());
      }
      setCandidateOffset(data.candidate_offset);
      setLastCreatedJob(null);
      setNotice(null);
    },
    onError: (error: Error, variables) => {
      if (variables?.requestKey !== activeRequestKey.current || variables?.requestId !== latestRequestId.current) return;
      setAnalyzingMode(null);
      setNotice({ type: 'error', text: error.message });
      setAnalysis(null);
    },
  });

  const createMutation = useMutation({
    mutationFn: async (variables?: CreateVariables) => {
      if (!analysis) {
        throw new Error('Analyze candidate profiles first.');
      }

      const maxProfiles =
        variables?.maxProfiles === undefined
          ? requestedBatchSize
          : variables.maxProfiles;

      return createMpsJob({
        site,
        start_id: analysis.start_id,
        end_id: analysis.end_id,
        ignore_missing_ids: !includeMissingIds,
        include_invalid: includeInvalid,
        invalid_last_checked_older_than_hours: includeInvalid ? recheckAgeHours : null,
        include_existing_users: includeExistingUsers,
        existing_last_checked_older_than_hours: includeExistingUsers
          ? recheckAgeHours
          : null,
        candidate_offset: variables?.candidateOffset ?? analysis.candidate_offset,
        max_profiles: maxProfiles,
        use_proxies: proxyMode !== 'none',
        proxy_mode: proxyMode,
        proxy_urls: proxyMode === 'custom' ? customProxyUrls : null,
        include_direct_connection: includeDirectConnection,
        max_route_hops: variables?.maxRouteHops ?? maxRouteHops,
        conclusive_miss_threshold: variables?.conclusiveMissThreshold ?? conclusiveMissThreshold,
        job_name: parseOptionalString(jobNameInput),
        created_by: 'webui_mps',
        candidate_count_hint: analysis.candidate_count,
      });
    },
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['jobs'] });
      void queryClient.invalidateQueries({ queryKey: ['queue-stats'] });
      setLastCreatedJob(result);
      setCandidateOffset(result.next_candidate_offset ?? result.candidate_offset);
      setNotice({
        type: 'success',
        text: buildMpsSuccessNotice(result),
      });
    },
    onError: (error: Error) => {
      setNotice({ type: 'error', text: error.message });
    },
  });

  const [discoveryResult, setDiscoveryResult] = useState<MPSBoundaryDiscoveryResponse | null>(null);
  const [isDiscoveryModalOpen, setIsDiscoveryModalOpen] = useState(false);

  const highestKnownId = useMemo(
    () => {
      const dbMax = siteBoundsQuery.data?.database_max_id ?? analysis?.database_max_id ?? null;
      const parsedEnd = parseOptionalInt(endIdInput);
      if (parsedEnd !== null && dbMax !== null) {
        return Math.max(parsedEnd, dbMax);
      }
      return parsedEnd ?? dbMax ?? parseOptionalInt(startIdInput) ?? null;
    },
    [
      analysis?.database_max_id,
      endIdInput,
      siteBoundsQuery.data?.database_max_id,
      startIdInput,
    ],
  );

  const handleApplyDiscovery = (
    startId: number,
    endId: number,
    data: MPSBoundaryDiscoveryResponse,
  ) => {
    setDiscoveryResult(data);
    setStartIdInput(String(startId));
    setEndIdInput(String(endId));
    invalidateAnalysis();
    setIsDiscoveryModalOpen(false);
    setNotice({
      type: 'success',
      text: `Discovered boundaries for ${data.site}: IDs ${data.discovered_start_id.toLocaleString()} – ${data.discovered_end_id.toLocaleString()}. Estimated population: ~${data.estimated_total_users.toLocaleString()} users (${Math.round(data.estimated_density * 100)}% density, ${Math.round(data.confidence_level * 100)}% confidence [${data.population_confidence_interval[0].toLocaleString()} – ${data.population_confidence_interval[1].toLocaleString()}]). Used ${data.total_probes_used} probes.`,
    });
  };

  const candidateRangesPreview = useMemo(
    () => analysis?.candidate_ranges_preview ?? analysis?.missing_ranges ?? [],
    [analysis],
  );
  const densePockets = useMemo(
    () => analysis?.dense_pockets ?? [],
    [analysis],
  );
  const candidatePreviewTruncated =
    analysis?.candidate_ranges_truncated ?? analysis?.candidate_preview_truncated ?? analysis?.missing_ranges_truncated ?? false;

  const adaptiveBatch = useMemo(
    () => calculateAdaptiveBatchSize(analysis, { includeMissingIds, routes }),
    [analysis, includeMissingIds, routes],
  );

  // Follow the adaptive batch size until the user overrides it (adjusted while
  // rendering, not in an effect).
  const adaptiveMaxProfiles =
    !isMaxProfilesOverridden && adaptiveBatch && adaptiveBatch.value > 0 ? String(adaptiveBatch.value) : null;
  const [syncedMaxProfiles, setSyncedMaxProfiles] = useState<string | null>(null);
  if (adaptiveMaxProfiles !== syncedMaxProfiles) {
    setSyncedMaxProfiles(adaptiveMaxProfiles);
    if (adaptiveMaxProfiles !== null) setMaxProfilesInput(adaptiveMaxProfiles);
  }

  const selectedProfiles = useMemo(() => {
    if (!analysis) return 0;
    if (!requestedBatchSize) return analysis.remaining_candidate_count;
    return Math.min(requestedBatchSize, analysis.remaining_candidate_count);
  }, [analysis, requestedBatchSize]);

  const proxyWarnings = useMemo(
    () => buildProxyWarnings(proxyPreviewQuery.data, selectedProfiles),
    [proxyPreviewQuery.data, selectedProfiles],
  );

  const combinedWarnings = useMemo(
    () => Array.from(new Set([...(analysis?.warnings ?? []), ...proxyWarnings])),
    [analysis?.warnings, proxyWarnings],
  );

  const nextBatchOffset = lastCreatedJob?.next_candidate_offset ?? null;
  const nextBatchSize = lastCreatedJob?.next_batch_size ?? requestedBatchSize;
  const hasCandidateSource = includeMissingIds || includeInvalid || includeExistingUsers;
  const hasRecheckSource = includeInvalid || includeExistingUsers;
  const invalidateAnalysis = () => {
    ++latestRequestId.current;
    setRoutesOpen(false);
    setAnalyzingMode(null);
    setAnalysisRevision((value) => value + 1);
    setAnalysis(null);
    setCandidateOffset(0);
    setLastCreatedJob(null);
    setNotice(null);
    setIsMaxProfilesOverridden(false);
  };

  const handleAnalyze = (
    nextOffset: number = candidateOffset,
    nextBatchSizeOverride?: number | null,
    bounded = true,
  ) => {
    window.clearTimeout(autoTimer.current);
    setNotice(null);
    setCandidateOffset(nextOffset);
    setAnalyzingMode(bounded ? 'quick' : 'full');
    analyzeMutation.mutate({
      candidateOffset: nextOffset,
      batchSize: nextBatchSizeOverride ?? requestedBatchSize,
      bounded,
      requestKey,
      requestId: ++latestRequestId.current,
    });
  };

  const { mutate: runAnalysis } = analyzeMutation;
  useEffect(() => {
    if (!includeMissingIds && !includeInvalid && !includeExistingUsers) return;
    const start = analysisScope.start_id;
    const end = analysisScope.end_id;
    if ((start !== null && start < 1) || (end !== null && end < 1) ||
        (start !== null && end !== null && start > end) ||
        (recheckAgeHours !== null && recheckAgeHours <= 0)) return;
    autoTimer.current = window.setTimeout(() => {
      setAnalyzingMode('quick');
      runAnalysis({
        request: { ...analysisScope, candidate_offset: 0, batch_size: null, bounded: true },
        requestKey,
        requestId: ++latestRequestId.current,
      });
    }, 400);
    return () => window.clearTimeout(autoTimer.current);
  }, [analysisScope, requestKey, runAnalysis, includeMissingIds, includeInvalid, includeExistingUsers, recheckAgeHours]);

  useEffect(() => {
    const dialog = routesDialog.current;
    if (routesOpen && dialog && !dialog.open) dialog.showModal();
    if (!routesOpen && dialog?.open) dialog.close();
  }, [routesOpen]);

  const handleCreate = (override?: CreateVariables) => {
    if (!analysis) {
      return;
    }

    createMutation.mutate(override);
  };

  return (
    <div className="tools-tool-container mps-space-map">
      <ToastPortal
        toast={notice?.type === 'success' ? { type: 'success', message: notice.text } : null}
        onDismiss={() => setNotice(null)}
      />
      {notice?.type === 'error' && <div className="tools-alert error" role="alert">{notice.text}</div>}
      <section className="mps-design" aria-label="ID-space map">
        <h2 className="mps-visually-hidden">ID-space map</h2>
        <MPSIdSpaceMap
          key={site}
          site={site}
          onSiteChange={(value) => { setSite(value); invalidateAnalysis(); }}
          analysis={analysis}
          sources={{ missing: includeMissingIds, invalid: includeInvalid, existing: includeExistingUsers }}
          loading={analyzeMutation.isPending}

        />
        <div className="mps-design-lower">
          <section className="mps-design-sources" aria-label="Sources">
            {[
              { label: 'New / missing', accessible: 'New or missing profiles', included: includeMissingIds, set: setIncludeMissingIds, count: analysis?.missing_count, detail: 'in range', source: 'missing' },
              { label: 'Previously not found', accessible: 'Previously not found profiles', included: includeInvalid, set: setIncludeInvalid, count: includeInvalid ? analysis?.invalid_eligible_count : analysis?.invalid_user_count, detail: includeInvalid ? 'eligible' : 'stored', source: 'invalid' },
              { label: 'Existing profiles', accessible: 'Existing profiles', included: includeExistingUsers, set: setIncludeExistingUsers, count: includeExistingUsers ? analysis?.existing_eligible_count : analysis?.existing_user_count, detail: includeExistingUsers ? 'eligible' : 'stored', source: 'existing' },
            ].map((source) => (
              <label key={source.source} className={`mps-design-switch ${source.included ? 'on' : ''} ${source.source}`}>
                <input type="checkbox" aria-label={source.accessible} checked={source.included} onChange={(event) => { source.set(event.target.checked); invalidateAnalysis(); }} />
                <span className="mps-design-switch-track" aria-hidden="true" />
                <span className="mps-design-switch-copy"><strong>{source.label}</strong><small>{analysis ? formatCount(source.count) : '—'} {source.detail}</small></span>
              </label>
            ))}
            {!hasCandidateSource && <p className="mps-map-warning">Select new/missing, previously not found, existing profiles, or any combination.</p>}
            {hasRecheckSource && (
              <div className="mps-design-cooldown">
                <strong>Recheck cooldown</strong>
                <div className="mps-design-duration">
                  <label className="tools-field"><span>Amount</span><input type="number" min={0.01} step="any" value={recheckAgeInput} onChange={(event) => { setRecheckAgeInput(event.target.value); invalidateAnalysis(); }} placeholder="No cooldown" /></label>
                  <label className="tools-field"><span>Unit</span><select value={recheckAgeUnit} onChange={(event) => { setRecheckAgeUnit(event.target.value as MPSRecheckUnit); invalidateAnalysis(); }}><option value="hours">Hours</option><option value="days">Days</option><option value="weeks">Weeks</option></select></label>
                </div>
                <p className="tools-helper">{formatRecheckWindow(recheckAgeInput, recheckAgeUnit)}</p>
              </div>
            )}
            <details className="mps-design-boundaries">
              <summary>ID boundaries</summary>
              <div className="mps-boundaries-controls">
                <button
                  type="button"
                  className="tools-btn tools-btn-secondary mps-discover-btn"
                  onClick={() => setIsDiscoveryModalOpen(true)}
                  title="Probe the site starting from our highest known ID to discover active user ID boundaries and estimate total population"
                >
                  <span>Discover Boundaries</span>
                </button>
                <small className="tools-helper">
                  Probes the site starting from our highest known ID to estimate active ID range and population.
                </small>
              </div>
              <label className="tools-field">
                <span>First profile ID (optional)</span>
                <input
                  type="number"
                  min={1}
                  value={startIdInput}
                  onChange={(event) => {
                    setStartIdInput(event.target.value);
                    invalidateAnalysis();
                  }}
                  placeholder={
                    siteBoundsQuery.data?.database_min_id
                      ? `Database min (${siteBoundsQuery.data.database_min_id.toLocaleString()})`
                      : 'Database minimum'
                  }
                />
              </label>
              <label className="tools-field">
                <span>Last profile ID (optional)</span>
                <input
                  type="number"
                  min={1}
                  value={endIdInput}
                  onChange={(event) => {
                    setEndIdInput(event.target.value);
                    invalidateAnalysis();
                  }}
                  placeholder={
                    siteBoundsQuery.data?.database_max_id
                      ? `Database max (${siteBoundsQuery.data.database_max_id.toLocaleString()})`
                      : 'Database maximum'
                  }
                />
              </label>
            </details>
          </section>
          <section className="mps-design-ranges" aria-label="Candidate range pockets">
            <div className="mps-pockets-body">
            <h4 className="mps-pockets-title">Dense pockets
              {densePockets.length > 0 && <span className="mps-id-map-help">
                <button type="button" aria-label="About dense pockets" aria-describedby="mps-pockets-help">ⓘ</button>
                <span role="tooltip" id="mps-pockets-help">Spatially aggregated candidate clusters across ID space.</span>
              </span>}
            </h4>
            {densePockets.length > 0 ? (
              <ul>
                {densePockets.map((pocket) => (
                  <li key={`${pocket.start_id}-${pocket.end_id}`}>
                    <button
                      type="button"
                      aria-label={`Target candidate range ${pocket.start_id.toLocaleString()} - ${pocket.end_id.toLocaleString()}`}
                      title={`${pocket.start_id.toLocaleString()} – ${pocket.end_id.toLocaleString()}: ${formatCount(pocket.candidate_count)} candidates (${pocket.density_percentage}% density)`}
                      onClick={() => {
                        setStartIdInput(String(pocket.start_id));
                        setEndIdInput(String(pocket.end_id));
                        invalidateAnalysis();
                      }}
                    >
                      <code>{formatCount(pocket.start_id)}</code>
                      <i style={{ width: `${(pocket.candidate_count / Math.max(1, ...densePockets.map((item) => item.candidate_count))) * 100}%` }} />
                      <small>
                        {formatCount(pocket.candidate_count)}
                        <span className="mps-pocket-pct"> ({pocket.density_percentage}%)</span>
                      </small>
                    </button>
                  </li>
                ))}
              </ul>
            ) : candidateRangesPreview.length ? (
              <ul>
                {candidateRangesPreview.map((range) => (
                  <li key={`${range.start_id}-${range.end_id}`}>
                    <button type="button" aria-label={`Target candidate range ${range.start_id.toLocaleString()} - ${range.end_id.toLocaleString()}`} title={`${range.start_id.toLocaleString()} – ${range.end_id.toLocaleString()}: ${formatCount(range.count)} candidates`} onClick={() => { setStartIdInput(String(range.start_id)); setEndIdInput(String(range.end_id)); invalidateAnalysis(); }}>
                      <code>{formatCount(range.start_id)}</code>
                      <i style={{ width: `${range.count / Math.max(1, ...candidateRangesPreview.map((item) => item.count)) * 100}%` }} />
                      <small>{formatCount(range.count)}</small>
                    </button>
                  </li>
                ))}
              </ul>
            ) : <p className="tools-helper">{analysis ? 'No candidate ranges in this preview.' : 'Quick analysis is loading candidate ranges…'}</p>}
            {densePockets.length === 0 && candidatePreviewTruncated ? (
              <p className="tools-helper">Showing complete ranges from the analysis preview. Additional ranges are omitted; unshown areas are unknown.</p>
            ) : null}
            {(candidateOffset > 0 || lastCreatedJob) && (
              <dl className="mps-created-job-details">
                {candidateOffset > 0 && <><dt>Candidate offset</dt><dd>{formatCount(candidateOffset)}</dd></>}
                {lastCreatedJob && <>
                  <dt>{['queued', 'materializing', 'finalizing'].includes(lastCreatedJob.job.materialization_status ?? '') ? 'Materializing' : 'Queued'}</dt><dd>{formatCount(lastCreatedJob.selected_profiles)}</dd>
                  <dt>Remaining</dt><dd>{formatCount(lastCreatedJob.remaining_candidate_count)}</dd>
                  <dt>Next Offset</dt><dd>{lastCreatedJob.next_candidate_offset !== null ? formatCount(lastCreatedJob.next_candidate_offset) : 'Complete'}</dd>
                </>}
              </dl>
            )}
            </div>
            {lastCreatedJob && (
              <div className="mps-continuation-actions">
                {lastCreatedJob.has_next_batch ? (
                  <>
                    <button
                      type="button"
                      className="tools-btn tools-btn-primary"
                      onClick={() => {
                        if (nextBatchOffset === null) {
                          return;
                        }
                        handleAnalyze(nextBatchOffset, nextBatchSize ?? null);
                      }}
                      disabled={analyzeMutation.isPending}
                    >
                      Analyze Next Batch
                    </button>
                    <button
                      type="button"
                      className="tools-btn tools-btn-secondary"
                      onClick={() => {
                        if (nextBatchOffset === null) {
                          return;
                        }
                        handleCreate({
                          candidateOffset: nextBatchOffset,
                          maxProfiles: nextBatchSize,
                        });
                      }}
                      disabled={createMutation.isPending}
                    >
                      Queue Next Batch
                    </button>
                  </>
                ) : (
                  <p className="tools-empty">
                    Candidate set exhausted. Adjust the range or filters to continue.
                  </p>
                )}
                {lastCreatedJob.job && (
                  <button
                    type="button"
                    className="tools-btn tools-btn-secondary"
                    onClick={() => setOpenedJob(lastCreatedJob.job)}
                  >
                    Open Job
                  </button>
                )}
              </div>
            )}
          </section>
          <aside className="mps-design-inspector" aria-label="Run">
            <div className="mps-run-body">
            <header>
              <h4>Run</h4>
              <button type="button" className="mps-proxy-button" aria-label="Configure lookup routes" title="Lookup routes" onClick={() => setRoutesOpen(true)}>
                <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true"><rect x="8" y="2" width="8" height="6" rx="1" /><path d="M12 8v5M4 17v-4h16v4" /><rect x="1" y="17" width="6" height="5" rx="1" /><rect x="17" y="17" width="6" height="5" rx="1" /></svg>
              </button>
            </header>
            <dl>
              <dt>IDs</dt><dd>{analysis ? formatCount(analysis.range_size) : '—'}</dd>
              <dt>Candidates</dt><dd className="accent">{analysis ? formatCount(analysis.candidate_count) : '—'}</dd>
              <dt>Batch size</dt><dd>{analysis ? formatCount(selectedProfiles) : '—'}</dd>
              <dt>Routes</dt><dd>{proxyPreviewQuery.data ? formatCount(proxyPreviewQuery.data.proxies_used + Number(proxyPreviewQuery.data.direct_connection_included)) : '—'}</dd>
              {(analysis?.population_estimate != null || discoveryResult?.estimated_total_users != null) && (
                <>
                  <dt>Est. Pop.</dt>
                  <dd
                    className="accent"
                    title={`Estimated total user population: ~${formatCount(analysis?.population_estimate ?? discoveryResult?.estimated_total_users)}`}
                  >
                    ~{formatCount(analysis?.population_estimate ?? discoveryResult?.estimated_total_users)}
                  </dd>
                </>
              )}
            </dl>
            <div className="tools-field">
              <div className="tools-field-label-row">
                <label htmlFor="mps-max-profiles">Max profiles (optional)</label>
                <button
                  type="button"
                  className="tools-inline-btn"
                  aria-label="Use adaptive batch size"
                  disabled={!adaptiveBatch || adaptiveBatch.value <= 0}
                  title={adaptiveBatch?.title}
                  onClick={() => {
                    if (adaptiveBatch && adaptiveBatch.value > 0) {
                      setMaxProfilesInput(String(adaptiveBatch.value));
                      setIsMaxProfilesOverridden(false);
                    }
                  }}
                >
                  Adaptive Batch
                </button>
              </div>
              <input
                id="mps-max-profiles"
                type="number"
                min={1}
                value={maxProfilesInput}
                onChange={(event) => {
                  setMaxProfilesInput(event.target.value);
                  setIsMaxProfilesOverridden(true);
                }}
                placeholder="All candidates (no limit)"
              />
              <small>Blank queues all remaining candidates.</small>
            </div>
            <details><summary>Job name</summary><label className="tools-field"><span>Job name (optional)</span><input type="text" value={jobNameInput} onChange={(event) => setJobNameInput(event.target.value)} placeholder="Auto-generated" /></label></details>
            {includeInvalid && analysis && !analysis.invalid_table_ready && <p className="mps-map-warning">Previously-not-found tracking unavailable. Run the database migrations before relying on this source.</p>}
            {combinedWarnings.map((warning) => <p className="mps-map-warning" key={warning}>{warning}</p>)}
            {analyzingMode === 'quick' && (
              <div className="mps-design-analysis" role="status">
                <span>Quick analysis running…</span>
              </div>
            )}
            </div>
            <div className="mps-run-actions">
            <button
              type="button"
              className="tools-btn tools-btn-secondary"
              aria-label="Full Analyze"
              disabled={analyzeMutation.isPending || !hasCandidateSource}
              onClick={() => handleAnalyze(0, null, false)}
            >
              {analyzingMode === 'full' && <span className="mps-analysis-spinner" aria-hidden="true" />}
              <span>Full Analyze</span>
            </button>
            <button type="button" className="tools-btn tools-btn-primary" aria-label="Create Job" disabled={!analysis || createMutation.isPending || analysis.remaining_candidate_count === 0} onClick={() => handleCreate()}>{createMutation.isPending ? 'Creating…' : `Queue ${formatCount(selectedProfiles)} profiles`}</button>
            </div>


          </aside>
        </div>
      </section>
          <dialog ref={routesDialog} className="mps-routes-dialog" aria-labelledby="mps-routes-title" onCancel={() => setRoutesOpen(false)} onClose={() => setRoutesOpen(false)} onClick={(event) => { if (event.target === event.currentTarget) setRoutesOpen(false); }}>
            <header className="mps-routes-header">
              <h2 id="mps-routes-title">Lookup routes</h2>
              <button type="button" className="tools-btn tools-btn-secondary" aria-label="Close lookup routes" onClick={() => setRoutesOpen(false)}>×</button>
            </header>
            <div className="mps-ops-controls">
              <label className="tools-field">
                <span>Proxy Strategy</span>
                <select
                  value={proxyMode}
                  onChange={(event) => setProxyMode(event.target.value as MPSProxyMode)}
                >
                  <option value="unassigned_only">Unassigned Only (default)</option>
                  <option value="all">All Configured Proxies</option>
                  <option value="custom">Custom Proxy URLs</option>
                  <option value="none">No Proxies</option>
                </select>
              </label>
            {/* Configurable Thresholds */}
            <div className="mps-thresholds-container">
              <div className="mps-thresholds-header">
                <span className="mps-thresholds-title">Configurable Thresholds</span>
                <small className="mps-thresholds-subtitle">
                  Configure route hop depth and inconclusive 404 exit criteria (1–5 hops/misses).
                </small>
              </div>
              <div className="tools-form-grid mps-thresholds-grid">
                <div className="tools-field">
                  <label htmlFor="mps-max-route-hops">Max Route Hops</label>
                  <input
                    id="mps-max-route-hops"
                    type="number"
                    min={1}
                    max={5}
                    value={maxRouteHopsInput}
                    onChange={(event) => setMaxRouteHopsInput(event.target.value)}
                    placeholder="3"
                  />
                  <small>Max proxy/direct hops to allocate per profile lookup (1–5, default 3).</small>
                </div>

                <div className="tools-field">
                  <label htmlFor="mps-conclusive-miss-threshold">Conclusive Miss Threshold</label>
                  <input
                    id="mps-conclusive-miss-threshold"
                    type="number"
                    min={1}
                    max={5}
                    value={conclusiveMissThresholdInput}
                    onChange={(event) => setConclusiveMissThresholdInput(event.target.value)}
                    placeholder="3"
                  />
                  <small>Distinct misses across routes before marking absent (1–5, default 3).</small>
                </div>
              </div>
            </div>

            {proxyMode !== 'none' && (
              <label className="tools-field-checkbox">
                <input
                  type="checkbox"
                  checked={includeDirectConnection}
                  onChange={(event) => setIncludeDirectConnection(event.target.checked)}
                />
                <span>Include direct connection as fallback route</span>
              </label>
            )}

            {proxyMode === 'custom' && (
              <label className="tools-field tools-field-full">
                <span>Custom proxy URLs (one per line)</span>
                <textarea
                  rows={5}
                  value={customProxyUrlsInput}
                  onChange={(event) => setCustomProxyUrlsInput(event.target.value)}
                  placeholder="socks5://127.0.0.1:9050"
                />
              </label>
            )}
          {/* ── Proxy list preview ── */}
          <div className="tools-proxy-preview">
            <div className="tools-proxy-preview-head">
              <h3>Lookup Routes</h3>
              {proxyPreviewQuery.isPending && <span className="tools-helper">Loading...</span>}
              {proxyPreviewQuery.isError && (
                <span className="tools-alert-text">Failed to load proxy list</span>
              )}
              {proxyPreviewQuery.data && (
                <span className="tools-helper">
                  {`${proxyPreviewQuery.data.proxies_used} proxies${proxyPreviewQuery.data.direct_connection_included ? ' + direct' : ''} / ${proxyPreviewQuery.data.proxies_configured} configured`}
                </span>
              )}
            </div>
            {proxyPreviewQuery.data &&
            (proxyPreviewQuery.data.direct_connection_included ||
              proxyPreviewQuery.data.proxy_urls.length > 0) ? (
              <ul className="tools-proxy-list">
                {proxyPreviewQuery.data.direct_connection_included && (
                  <li>
                    <code>Direct connection (raw IP)</code>
                  </li>
                )}
                {proxyPreviewQuery.data.proxy_urls.map((url) => (
                  <li key={url}>
                    <code>{url}</code>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="tools-empty">No proxies selected for this mode.</p>
            )}
          </div>

          </div>
          </dialog>


      {isDiscoveryModalOpen && (
        <MPSBoundaryDiscoveryModal
          isOpen={isDiscoveryModalOpen}
          site={site}
          defaultStartingId={highestKnownId}
          onClose={() => setIsDiscoveryModalOpen(false)}
          onApply={handleApplyDiscovery}
        />
      )}
      {openedJob && <JobDetailsModal key={openedJob.job_id} job={openedJob} onClose={() => setOpenedJob(null)} />}
    </div>
  );
}
