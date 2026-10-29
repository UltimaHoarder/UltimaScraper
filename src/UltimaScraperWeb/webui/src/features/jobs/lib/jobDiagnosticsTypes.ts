import type {
  JobRouteLookupStat,
  JobRuntimeSample,
  MPSRefillTraceEvent,
} from '../../../api/types/jobs';

export interface TelemetrySnapshot {
  timestamp: number; // ms
  intervalStartTimestamp: number;
  completedDelta: number;
  itemsDelta: number;
  itemsAreAuthoritative: boolean;
  itemsProcessed: number;
  completedTasks: number;
  inflightTasks: number;
  readyTasks: number;
  failedTasks: number;
  throughputItemsPerSec: number;
  throughputTasksPerSec: number;
  p50Latency: number;
  p95Latency: number;
  activeProxies: number;
  errorCount: number;
}

export interface TelemetrySamplingInputs {
  observedAt: number;
  completed: number;
  items: number;
  itemsAreAuthoritative: boolean;
  inflight: number;
  ready: number;
  failed: number;
  errors: number;
  p50Latency: number;
  p95Latency: number;
  totalProxyCapacity: number;
  isLiveJob: boolean;
}

export interface LatencyPercentiles {
  p50: number;
  p90: number;
  p95: number;
  p99: number;
  sampleCount: number;
}

export interface ProxyCapacityStats {
  totalRoutes: number;
  enabledProxies: number;
  directRoutes: number;
  activeRoutes: number;
  utilizationPercent: number;
  isNearCapacity: boolean;
  isSaturated: boolean;
  capacityUnit?: 'connection_slots';
  totalSlots?: number;
  activeSlots?: number;
}

export interface HttpStatusBreakdown {
  ok200: number;
  rateLimit429: number;
  forbidden403: number;
  notFound404: number;
  serverError5xx: number;
  timeoutErrors: number;
  otherErrors: number;
  totalObserved: number;
}

export interface ThroughputStats {
  currentItemsPerSec: number;
  currentTasksPerSec: number;
  sma1mItemsPerSec: number;
  sma1mTasksPerSec: number;
  sma5mItemsPerSec: number;
  sma5mTasksPerSec: number;
  trend: 'increasing' | 'decreasing' | 'steady';
  trendDeltaPercent: number;
  /** The unit represented by the displayed rate when item totals are unavailable. */
  throughputUnit?: 'items' | 'tasks';
  currentSampleDurationSec?: number;
  sma1mWindowSec?: number;
}

export interface ErrorVelocityStats {
  totalErrors: number;
  errorsLast60s: number;
  safetyThresholdLimit: number;
  safetyMarginPercent: number;
  trend: 'stable' | 'elevated' | 'critical';
  rate429Count: number;
  rate429PerMin: number;
  rate429Scope?: 'job_average' | 'observed_window';
  errorWindowScope?: 'observed_window' | 'job_snapshot';
  errorWindowSeconds?: number;
}

export interface TelemetryQuality {
  loadedTaskCount: number;
  totalTaskCount: number;
  coveragePercent: number;
  isCompleteTaskSample: boolean;
  throughputUnit: 'items' | 'tasks';
  peakScope: 'complete_job' | 'loaded_sample';
}

export interface ProxyAnomaly {
  proxyUrl: string;
  displayUrl: string;
  group: string | null;
  country: string | null;
  countryFlag: string | null;
  totalAttempts: number;
  failures: number;
  rateLimits429: number;
  timeouts: number;
  failureRatePercent: number;
  avgLatencySec: number;
  anomalyScore: number;
  status: 'critical' | 'degraded' | 'healthy';
  primaryIssue: string;
}

export interface FinalReportSummary {
  jobOutcome: string;
  totalDurationFormatted: string;
  totalDurationSec: number;
  metadataDurationSec?: number | null;
  telemetryActiveWindowSec?: number | null;
  durationDiscrepancyPercent?: number | null;
  durationSource?: 'job_metadata' | 'task_active_window';
  overallAvgItemsPerSec: number;
  overallAvgTasksPerSec: number;
  peakItemsPerSec: number;
  efficiencyPercent: number;
  proxyBottleneckFactor: number;
  theoreticalMaxItemsPerSec: number;
  theoreticalProxyMaxItemsPerSec?: number;
  theoreticalWorkerMaxItemsPerSec?: number;
  capacityModelBottleneck?: 'proxy_routes' | 'worker_slots';
  failedTaskCount?: number;
  terminationReason: string | null;
  healthyProxyCount: number;
  degradedProxyCount: number;
  criticalProxyCount: number;
  avgActiveConcurrency: number;
  avgActiveProxyRoutes: number;
  avgActiveProxyUtilization: number;
  recommendations: string[];
  throughputUnit?: 'items' | 'tasks';
  peakScope?: 'complete_job' | 'loaded_sample';
  peakWasCapped?: boolean;
  runtimeTelemetryComplete?: boolean;
  meanTaskDurationSec?: number | null;
  meanRouteActiveDurationSec?: number | null;
  meanRouteAttemptDurationSec?: number | null;
  routeAttemptsPerTask?: number | null;
  routeLookupStats?: Record<string, JobRouteLookupStat> | null;
  meanHandlerGuestInitMs?: number | null;
  handlerGuestInitCount?: number;
  meanHandlerInitialLookupMs?: number | null;
  handlerInitialLookupCount?: number;
  meanHandlerRefreshApiMs?: number | null;
  handlerRefreshApiCount?: number;
  meanHandlerFallbackRetryMs?: number | null;
  handlerFallbackRetryCount?: number;
  meanHandlerSerializationMs?: number | null;
  handlerSerializationCount?: number;
  meanHandlerResidualMs?: number | null;
  dominantHandlerSubphase?: string | null;
  meanQueueWaitSec?: number | null;
  meanSetupSec?: number | null;
  setupSubphases?: Record<string, { mean_ms: number; count: number; mean_ms_per_observation?: number }> | null;
  dominantSetupSubphase?: string | null;
  meanHandlerSec?: number | null;
  meanWriterSec?: number | null;
  meanPostSec?: number | null;
  meanReleaseSec?: number | null;
  activeWindowThroughput?: number | null;
  steadyStateThroughput?: number | null;
  steadyStateCapacityItemsPerSec?: number | null;
  steadyStateEfficiencyPercent?: number | null;
  rampDrainPercent?: number | null;
  meanClaimWaitMs?: number | null;
  meanWriterAdmissionMs?: number | null;
  meanWriterAdmissionSerializationMs?: number | null;
  meanWriterAdmissionCapacityWaitMs?: number | null;
  meanWriterAdmissionRedisMs?: number | null;
  meanWriterAdmissionOverheadDetailMs?: number | null;
  meanWriterQueueMs?: number | null;
  meanWriterExecutionMs?: number | null;
  meanWriterCommitMs?: number | null;
  meanWriterOverheadMs?: number | null;
  meanWriterBatchPeerWorkMs?: number | null;
  meanWriterDeliveryMs?: number | null;
  meanWriterResultPublicationMs?: number | null;
  meanWriterResultObservationMs?: number | null;
  meanWriterResultDeliveryResidualMs?: number | null;
  writerResultDeliverySplitCoveragePercent?: number | null;
  writerTimedSubmits?: number;
  writerSubmitsPerTask?: number | null;
  writerSubmitsPerSec?: number | null;
  writerResultCacheHits?: number;
  writerReceiptFallbacks?: number;
  writerResultCacheHitPercent?: number | null;
  writerSplitMissingReasons?: Record<string, number>;
  writerOperationStats?: Record<string, {
    count: number;
    mean_batch_commands: number;
    mean_batch_wall_ms: number;
    receipt_phases_count?: number;
    mean_receipt_lock_ms?: number;
    mean_receipt_read_ms?: number;
    mean_write_fence_ms?: number;
  }>;
  writerDomainStats?: Record<string, {
    count: number;
    mean_batch_commands: number;
    mean_batch_wall_ms: number;
  }>;
  writerTimingCoveragePercent?: number | null;
  dominantWriterSubphase?: string | null;
  meanWriterConnectionCheckoutMs?: number | null;
  meanWriterReceiptLookupMs?: number | null;
  meanWriterReceiptFinalizeMs?: number | null;
  meanWriterPayloadMs?: number | null;
  meanWriterUserRowMs?: number | null;
  meanWriterAliasMs?: number | null;
  meanWriterAuthorityMs?: number | null;
  writerAuthorityRowsExamined?: number;
  writerAuthorityRowsSkipped?: number;
  writerAuthorityRowsUpserted?: number;
  writerAuthoritySkipPercent?: number | null;
  meanWriterProfileMs?: number | null;
  meanWriterSocialMs?: number | null;
  meanWriterFlushMs?: number | null;
  dominantWriterExecutionSubphase?: string | null;
  meanWriterQueueCommandsAtStart?: number | null;
  maxWriterQueueCommandsAtStart?: number | null;
  meanWriterQueueBytesAtStart?: number | null;
  maxWriterQueueBytesAtStart?: number | null;
  meanWriterActiveLanes?: number | null;
  maxWriterActiveLanes?: number | null;
  meanWriterBatchCommands?: number | null;
  meanWriterBatchFillPercent?: number | null;
  meanWriterLaneIdleMs?: number | null;
  meanWriterLanePredecessorWaitMs?: number | null;
  meanWriterRefillWaitMs?: number | null;
  writerConfiguredConcurrency?: number | null;
  writerConfiguredBatchSize?: number | null;
  writerWindowCommands?: number | null;
  writerQueueMaxCommands?: number | null;
  writerQueueMaxBytes?: number | null;
  writerRefillMinCommands?: number | null;
  writerRefillMinCommandsPerLane?: number | null;
  maxWorkerCompletionGapMs?: number | null;
  readyQueueRecoveryCount?: number;
  readyQueueRecoveredTasks?: number;
  readyNonemptyPercent?: number | null;
  readyNonemptySamples?: number | null;
  readySampleCount?: number | null;
  readyTimelineNonemptyPercent?: number | null;
  readyTimelineIntervalCount?: number;
  readyTimelineCoveredSeconds?: number;
  steadyReadyTimelineNonemptyPercent?: number | null;
  steadyReadyTimelineCoveredSeconds?: number;
  meanReadyDepth?: number | null;
  workersSeen?: number | null;
  expectedWorkers?: number | null;
  timeWeightedParticipatingWorkers?: number | null;
  timeWeightedEffectiveWorkerCapacity?: number | null;
  occupancyGapClassification?:
    | 'routing_stall'
    | 'ramp_drain'
    | 'worker_availability'
    | 'intermittent_ready_supply'
    | 'queue_starvation'
    | 'steady_state_saturated'
    | 'insufficient_data';
  occupancyGapExplanation?: string | null;
}

export type BottleneckState =
  | 'routing_stall'
  | 'claim_refill'
  | 'proxy_saturated'
  | 'worker_constrained'
  | 'writer_constrained'
  | 'handler_constrained'
  | 'setup_constrained'
  | 'terminal_constrained'
  | 'release_constrained'
  | 'route_constrained'
  | 'queue_starved'
  | 'insufficient_data'
  | 'optimal';

export interface BottleneckAnalysis {
  state: BottleneckState;
  label: string;
  explanation: string;
  rootCauseFindings: string[];
}

export interface ThroughputLossFactor {
  factor: string;
  severity: 'critical' | 'high' | 'moderate' | 'low';
  estimatedLossItemsPerSec: number;
  description: string;
  remedy: string;
}

export interface ThroughputDiagnostics {
  theoreticalProxyMaxItemsPerSec: number;
  theoreticalWorkerMaxItemsPerSec: number;
  governingCeilingItemsPerSec: number;
  governingBottleneck: 'proxy_capacity' | 'worker_concurrency' | 'upstream_latency';
  activeConcurrency: number;
  idleProxyRoutes: number;
  idleProxyPercent: number;
  proxyUtilizationPercent: number;
  workerUtilizationPercent: number;
  workerPoolSize: number;
  workerConcurrencyDemand: number;
  targetConcurrency: number;
  latencySpreadRatio: number;
  tailLatencyDragPercent: number;
  peakToAvgRatio: number;
  lossFactors: ThroughputLossFactor[];
}

export interface DurationBreakdownTelemetry {
  taskCount: number;
  expectedTaskCount: number;
  meanTaskDurationSec: number | null;
  meanQueueWaitSec: number | null;
  meanSetupSec: number | null;
  meanHandlerSec: number | null;
  meanWriterSec: number | null;
  meanPostSec: number | null;
  meanReleaseSec: number | null;
}

export interface JobDiagnosticsTelemetry {
  snapshots: TelemetrySnapshot[];
  chartSnapshots: TelemetrySnapshot[];
  jobRuntimeSamples?: JobRuntimeSample[];
  mpsRefillTrace: MPSRefillTraceEvent[];
  guestAuthStats?: Record<string, { ms: number; count: number }>;
  terminalStats?: Record<string, { ms: number; count: number }>;
  ledgerStats?: Record<string, { ms: number; count: number }>;
  throughput: ThroughputStats;
  latencyPercentiles: LatencyPercentiles;
  proxyCapacity: ProxyCapacityStats;
  httpDistribution: HttpStatusBreakdown;
  errorVelocity: ErrorVelocityStats;
  proxyAnomalies: ProxyAnomaly[];
  finalSummary: FinalReportSummary;
  bottleneckAnalysis: BottleneckAnalysis;
  throughputDiagnostics?: ThroughputDiagnostics;
  durationBreakdown?: DurationBreakdownTelemetry | null;
  runningTasksCount: number;
  readyTasksCount: number;
  totalTasksCount: number;
  completedTasksCount: number;
  isLive: boolean;
  lastSampleTime: number;
  quality?: TelemetryQuality;
}
