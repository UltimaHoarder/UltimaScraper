import {
  useMemo,
  useState,
  type ReactNode,
  type RefObject,
} from 'react';

import type { TaskDetail, TaskStats } from '../../../api/types/jobs';
import type { NetworkProxy } from '../../../api/types/network';
import type { WebSocketEvent } from '../../../hooks/useWebSocket';
import type { JobEtaResult } from '../lib/jobEta';
import { TaskEvidencePages } from './TaskEvidencePages';
import {
  getTaskDownloadErrorCount,
  streamTaskKey,
} from '../lib/jobUtils';
import {
  ACTIVE_TASK_STATES,
  asNumber,
  asString,
  dependencyIds,
  downloadResults,
  fileName,
  formatRate,
  formatTransferBytes,
  mediaGlyph,
  mediaKind,
  mediaPreviewUrls,
  mediaProgress,
  normalizedMediaState,
  parseLiveTransfer,
  resultMetrics,
  RUNBOOK_STAGES,
  taskAttempt,
  taskDuration,
  taskHopUsed,
  taskIsGeoBlocked,
  taskMessage,
  taskProgressPercent,
  taskStage,
  taskStatusTone,
  taskTitle,
  taskTypeLabel,
  taskTypeStage,
  taskWorker,
  TERMINAL_TASK_STATES,
  type RunbookMediaEntry,
  type RunbookStageId,
} from '../lib/runbookModel';
import {
  formatProxyHost,
  getTaskProxySummary,
} from '../lib/taskProxyUtils';
import { copyText } from '../../../utils/clipboard';

interface JobRunbookPipelineProps {
  jobId: string;
  tasks: TaskDetail[];
  taskStats?: TaskStats;
  networkProxies?: NetworkProxy[];
  workerId?: string | null;
  liveEvent?: WebSocketEvent | null;
  isStreaming: boolean;
  isLiveJob: boolean;
  canStreamTasks: boolean;
  streamMaxTotalTasks: number;
  emptyMessage: string;
  hasMoreTasks: boolean;
  isLoadingMoreTasks: boolean;
  onLoadMoreTasks: () => void;
  pipelineRef: RefObject<HTMLDivElement | null>;
  taskStateFilter: string;
  onTaskStateFilterChange: (value: string) => void;
  taskTypeFilter: string;
  onTaskTypeFilterChange: (value: string) => void;
  taskTypeOptions: string[];
  hopUsedMin: string;
  onHopUsedMinChange: (value: string) => void;
  hopUsedMax: string;
  onHopUsedMaxChange: (value: string) => void;
  geoBlockedFilter: boolean;
  onGeoBlockedFilterChange: (value: boolean) => void;
  errorOnlyFilter: boolean;
  onErrorOnlyFilterChange: (value: boolean) => void;
  taskStateFilters: Array<{ value: string; label: string }>;
  notices?: ReactNode;
  actions?: ReactNode;
  jobEta?: JobEtaResult | null;
}

function MediaPreview({
  entry,
  task,
  jobId,
  compact = false,
}: {
  entry: RunbookMediaEntry;
  task: TaskDetail;
  jobId: string;
  compact?: boolean;
}) {
  const kind = mediaKind(entry.path || entry.url);
  const previewUrls = useMemo(
    () => mediaPreviewUrls(entry, task, jobId),
    [entry, jobId, task],
  );
  const previewSetKey = `${entry.key}\n${previewUrls.join('\n')}`;
  const [previewState, setPreviewState] = useState({ key: previewSetKey, index: 0 });
  const previewIndex = previewState.key === previewSetKey ? previewState.index : 0;
  const previewUrl = previewUrls[previewIndex] ?? null;

  const useNextPreview = () => {
    setPreviewState((current) => {
      const currentIndex = current.key === previewSetKey ? current.index : 0;
      return {
        key: previewSetKey,
        index: currentIndex + 1 < previewUrls.length ? currentIndex + 1 : previewUrls.length,
      };
    });
  };

  return (
    <span className={`jdm-runbook-media-preview is-${kind} ${compact ? 'is-compact' : ''}`}>
      <span className="jdm-runbook-media-preview-fallback" aria-hidden="true">
        {mediaGlyph(kind)}
      </span>
      {previewUrl && kind === 'image' ? (
        <img
          src={previewUrl}
          alt=""
          loading="lazy"
          onError={useNextPreview}
        />
      ) : null}
      {previewUrl && kind === 'video' ? (
        <video
          src={previewUrl}
          muted
          playsInline
          preload="metadata"
          aria-label={`Preview of ${fileName(entry.path || entry.url) || 'downloaded video'}`}
          onError={useNextPreview}
        />
      ) : null}
    </span>
  );
}

export function JobRunbookPipeline({
  jobId,
  tasks,
  taskStats,
  networkProxies,
  workerId,
  liveEvent,
  isStreaming,
  isLiveJob,
  canStreamTasks,
  streamMaxTotalTasks,
  emptyMessage,
  hasMoreTasks,
  isLoadingMoreTasks,
  onLoadMoreTasks,
  pipelineRef,
  taskStateFilter,
  onTaskStateFilterChange,
  taskTypeFilter,
  onTaskTypeFilterChange,
  taskTypeOptions,
  hopUsedMin,
  onHopUsedMinChange,
  hopUsedMax,
  onHopUsedMaxChange,
  geoBlockedFilter,
  onGeoBlockedFilterChange,
  errorOnlyFilter,
  onErrorOnlyFilterChange,
  taskStateFilters,
  notices,
  actions,
  jobEta,
}: JobRunbookPipelineProps) {
  const [selectedTaskKey, setSelectedTaskKey] = useState<string | null>(null);
  const [selectedMediaKey, setSelectedMediaKey] = useState<string | null>(null);

  const filteredTasks = useMemo(
    () => tasks.filter((task) => {
      const hopUsed = taskHopUsed(task, networkProxies);
      const minimum = asNumber(hopUsedMin);
      const maximum = asNumber(hopUsedMax);
      if (minimum !== null && hopUsed < minimum) return false;
      if (maximum !== null && hopUsed > maximum) return false;
      if (geoBlockedFilter && !taskIsGeoBlocked(task, networkProxies)) return false;
      return true;
    }),
    [geoBlockedFilter, hopUsedMax, hopUsedMin, networkProxies, tasks],
  );

  const hopRangeActive = Boolean(hopUsedMin || hopUsedMax);
  const hasClientTaskFilters = hopRangeActive || geoBlockedFilter;

  const defaultTask = useMemo(
    () =>
      filteredTasks.find((task) => ACTIVE_TASK_STATES.has(String(task.status).toLowerCase())) ??
      filteredTasks.find((task) => String(task.status).toLowerCase() === 'failed') ??
      filteredTasks.find((task) => taskStage(task) === 'download' && downloadResults(task).length > 0) ??
      filteredTasks.find((task) => taskStage(task) === 'download') ??
      filteredTasks[0] ??
      null,
    [filteredTasks],
  );

  const selectedTask = useMemo(
    () => filteredTasks.find((task) => streamTaskKey(task) === selectedTaskKey) ?? defaultTask,
    [defaultTask, filteredTasks, selectedTaskKey],
  );

  const selectedProxySummary = useMemo(
    () => (selectedTask ? getTaskProxySummary(selectedTask, networkProxies) : null),
    [selectedTask, networkProxies],
  );

  const stageGroups = useMemo(() => {
    const authoritativeCounts = Object.entries(taskStats?.task_type_counts ?? {}).reduce(
      (counts, [taskType, count]) => {
        const stage = taskTypeStage(taskType);
        counts[stage] += count;
        return counts;
      },
      { prepare: 0, scrape: 0, download: 0, finish: 0 } as Record<RunbookStageId, number>,
    );

    return RUNBOOK_STAGES.map((stage) => {
      const stageTasks = filteredTasks.filter((task) => taskStage(task) === stage.id);
      return {
        ...stage,
        tasks: stageTasks,
        total: hasClientTaskFilters ? stageTasks.length : Math.max(stageTasks.length, authoritativeCounts[stage.id]),
      };
    }).filter((stage) => stage.tasks.length > 0);
  }, [filteredTasks, hasClientTaskFilters, taskStats?.task_type_counts]);

  const selectedMetrics = resultMetrics(selectedTask);
  const activeFilterCount = [
    taskStateFilter,
    taskTypeFilter,
    hopRangeActive ? 'hop-range' : '',
    geoBlockedFilter ? 'geo-blocked' : '',
    errorOnlyFilter ? 'errors' : '',
  ].filter(Boolean).length;
  const latestLiveTransfer = parseLiveTransfer(liveEvent, jobId);
  const selectedLiveTransfer =
    selectedTask?.task_id && latestLiveTransfer?.taskId === selectedTask.task_id
      ? latestLiveTransfer
      : null;
  const dependencies = selectedTask ? dependencyIds(selectedTask) : [];
  const selectedProgress = selectedTask ? taskProgressPercent(selectedTask) : 0;
  const selectedDownloadErrors = selectedTask ? getTaskDownloadErrorCount(selectedTask) : 0;
  const metricSpeed = asNumber(selectedMetrics.speed_bps ?? selectedMetrics.avg_speed_bps);
  const speedBps = selectedLiveTransfer?.speedBps ?? metricSpeed;
  const mediaEntries: RunbookMediaEntry[] = [];
  if (selectedTask) {
    if (selectedLiveTransfer) {
      mediaEntries.push({
        key: `live-${selectedLiveTransfer.mediaId || selectedLiveTransfer.path || selectedLiveTransfer.taskId}`,
        resultIndex: null,
        mediaId: selectedLiveTransfer.mediaId,
        path: selectedLiveTransfer.path,
        url: selectedLiveTransfer.url,
        status: selectedLiveTransfer.status || 'downloading',
        processedBytes: selectedLiveTransfer.processedBytes,
        expectedBytes: selectedLiveTransfer.expectedBytes,
        speedBps: selectedLiveTransfer.speedBps,
        isLive: true,
      });
    }

    for (const [index, entry] of downloadResults(selectedTask).entries()) {
      const mediaId = entry.media_id == null ? null : String(entry.media_id);
      const path = asString(entry.path);
      const url = asString(entry.url);
      const key = `result-${mediaId || path || url || index}`;
      const duplicatesLive = mediaEntries.some(
        (candidate) =>
          (mediaId && candidate.mediaId === mediaId) ||
          (path && candidate.path === path) ||
          (url && candidate.url === url),
      );
      if (duplicatesLive) continue;
      mediaEntries.push({
        key,
        resultIndex: index,
        mediaId,
        path,
        url,
        status: asString(entry.status) || 'complete',
        processedBytes: asNumber(entry.bytes_written ?? entry.processed_bytes ?? entry.size),
        expectedBytes: asNumber(entry.expected_bytes ?? entry.total_bytes ?? entry.file_size ?? entry.size),
        speedBps: asNumber(entry.speed_bps ?? entry.avg_speed_bps),
        isLive: false,
      });
    }
  }
  const selectedMedia =
    mediaEntries.find((entry) => entry.key === selectedMediaKey) ?? mediaEntries[0] ?? null;
  const selectedMediaPercent = selectedMedia ? mediaProgress(selectedMedia) : 0;
  const selectedMediaState = selectedMedia
    ? normalizedMediaState(selectedMedia.status, selectedMedia.isLive)
    : null;
  const selectedMediaUrl = selectedMedia && selectedTask
    ? (mediaPreviewUrls(selectedMedia, selectedTask, jobId)[0] ?? null)
    : null;
  const activeMediaCount = mediaEntries.filter(
    (entry) => normalizedMediaState(entry.status, entry.isLive) === 'downloading',
  ).length;
  const queuedMediaCount = mediaEntries.filter(
    (entry) => normalizedMediaState(entry.status, entry.isLive) === 'queued',
  ).length;
  const completeMediaCount = mediaEntries.filter(
    (entry) => normalizedMediaState(entry.status, entry.isLive) === 'complete',
  ).length;
  const loadedCounts = useMemo(
    () =>
      tasks.reduce(
        (counts, task) => {
          const status = String(task.status || '').toLowerCase();
          if (ACTIVE_TASK_STATES.has(status)) counts.running += 1;
          if (status === 'pending' || status === 'ready') counts.ready += 1;
          if (status === 'blocked') counts.blocked += 1;
          if (status === 'deferred') counts.deferred += 1;
          if (status === 'completed') counts.completed += 1;
          if (status === 'failed') counts.failed += 1;
          if (TERMINAL_TASK_STATES.has(status)) counts.terminal += 1;
          return counts;
        },
        { running: 0, ready: 0, blocked: 0, deferred: 0, completed: 0, failed: 0, terminal: 0 },
      ),
    [tasks],
  );
  const loadedTasksCoverJob =
    tasks.length > 0 && (!taskStats || (taskStats.total > 0 && tasks.length >= taskStats.total));
  const runningCount = loadedTasksCoverJob ? loadedCounts.running : (taskStats?.inflight ?? 0);
  const readyCount = loadedTasksCoverJob ? loadedCounts.ready : (taskStats?.ready ?? 0);
  const blockedCount = loadedTasksCoverJob ? loadedCounts.blocked : (taskStats?.blocked ?? 0);
  const deferredCount = loadedTasksCoverJob ? loadedCounts.deferred : (taskStats?.deferred ?? 0);
  const completedCount = loadedTasksCoverJob ? loadedCounts.completed : (taskStats?.completed ?? 0);
  const failedCount = loadedTasksCoverJob ? loadedCounts.failed : (taskStats?.failed ?? 0);
  const terminalCount = loadedTasksCoverJob
    ? loadedCounts.terminal
    : taskStats
      ? taskStats.completed + taskStats.failed
      : loadedCounts.terminal;
  const totalCount = hasClientTaskFilters
    ? filteredTasks.length
    : loadedTasksCoverJob
      ? tasks.length
      : (taskStats?.total ?? tasks.length);

  return (
    <div className="jdm-runbook-shell">
      <div className="jdm-runbook-grid">
        <nav className="jdm-runbook-outline" aria-label="Job execution runbook" ref={pipelineRef}>
          <div className="jdm-runbook-section-heading">
            <div>
              <span>Execution plan</span>
              <strong>
                {totalCount.toLocaleString()} ordered task{totalCount === 1 ? '' : 's'}
              </strong>
            </div>
            <details className="jdm-runbook-filters">
              <summary>{activeFilterCount > 0 ? `Filter · ${activeFilterCount} active` : 'Filter'}</summary>
              <div className="jdm-runbook-filter-popover">
                <label className="jdm-pipeline-filter">
                  <span>State</span>
                  <select
                    aria-label="Task state filter"
                    value={taskStateFilter}
                    onChange={(event) => onTaskStateFilterChange(event.target.value)}
                  >
                    {taskStateFilters.map((option) => (
                      <option key={option.value || 'all'} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="jdm-pipeline-filter">
                  <span>Task type</span>
                  <select
                    aria-label="Task type filter"
                    value={taskTypeFilter}
                    onChange={(event) => onTaskTypeFilterChange(event.target.value)}
                  >
                    <option value="">All task types</option>
                    {taskTypeOptions.map((taskType) => (
                      <option key={taskType} value={taskType}>
                        {taskTypeLabel(taskType)}
                      </option>
                    ))}
                  </select>
                </label>
                <div className="jdm-pipeline-filter jdm-pipeline-filter-range">
                  <span>Hops used</span>
                  <div>
                    <input
                      aria-label="Minimum hops used"
                      inputMode="numeric"
                      min="1"
                      placeholder="Min"
                      type="number"
                      value={hopUsedMin}
                      onChange={(event) => onHopUsedMinChange(event.target.value)}
                    />
                    <input
                      aria-label="Maximum hops used"
                      inputMode="numeric"
                      min="1"
                      placeholder="Max"
                      type="number"
                      value={hopUsedMax}
                      onChange={(event) => onHopUsedMaxChange(event.target.value)}
                    />
                  </div>
                </div>
                <label className="jdm-pipeline-toggle">
                  <input
                    aria-label="Geo-blocked tasks filter"
                    type="checkbox"
                    checked={geoBlockedFilter}
                    onChange={(event) => onGeoBlockedFilterChange(event.target.checked)}
                  />
                  <span>Geo-blocked only</span>
                </label>
                <label className="jdm-pipeline-toggle">
                  <input
                    aria-label="Errors only filter"
                    type="checkbox"
                    checked={errorOnlyFilter}
                    onChange={(event) => onErrorOnlyFilterChange(event.target.checked)}
                  />
                  <span>Errors only</span>
                </label>
                {activeFilterCount > 0 && (
                  <button
                    type="button"
                    className="jdm-runbook-filter-clear"
                    onClick={() => {
                      onTaskStateFilterChange('');
                      onTaskTypeFilterChange('');
                      onHopUsedMinChange('');
                      onHopUsedMaxChange('');
                      onGeoBlockedFilterChange(false);
                      onErrorOnlyFilterChange(false);
                    }}
                  >
                    Clear all filters
                  </button>
                )}
                <div className="jdm-runbook-stream-meta">
                  <span className={isStreaming ? 'is-live' : ''}>
                    {isStreaming
                      ? 'Live task stream'
                      : isLiveJob && !canStreamTasks
                        ? `Paged view above ${streamMaxTotalTasks.toLocaleString()} tasks`
                        : 'Paged task history'}
                  </span>
                  <small>{readyCount} ready · {runningCount} inflight · {completedCount} complete</small>
                </div>
              </div>
            </details>
          </div>

          {filteredTasks.length === 0 ? (
            <div className="jdm-empty">
              {hasClientTaskFilters && tasks.length > 0 ? 'No tasks match the selected task filters.' : emptyMessage}
            </div>
          ) : (
            stageGroups.map((stage, stageIndex) => (
              <section key={stage.id} className="jdm-runbook-stage">
                <div className="jdm-runbook-stage-title">
                  <span>{stageIndex + 1}</span>
                  <strong>{stage.label}</strong>
                  <small>
                    {stage.total > stage.tasks.length
                      ? `${stage.tasks.length.toLocaleString()} loaded of ${stage.total.toLocaleString()} tasks`
                      : `${stage.total.toLocaleString()} task${stage.total === 1 ? '' : 's'}`}
                    {stage.id === 'download'
                      ? ` · ${stage.tasks.reduce((count, task) => count + downloadResults(task).length, 0)} files`
                      : ''}
                  </small>
                </div>
                {stage.tasks.map((task) => {
                  const key = streamTaskKey(task);
                  const percent = taskProgressPercent(task);
                  const tone = taskStatusTone(String(task.status || 'pending'));
                  const taskProxy = getTaskProxySummary(task, networkProxies);
                  return (
                    <button
                      type="button"
                      key={key}
                      className={selectedTask && streamTaskKey(selectedTask) === key ? 'is-selected' : ''}
                      aria-pressed={selectedTask ? streamTaskKey(selectedTask) === key : false}
                      onClick={() => setSelectedTaskKey(key)}
                    >
                      <i className={`jdm-runbook-dot jdm-runbook-dot-${tone}`} aria-hidden="true" />
                      <span>
                        <strong>{taskTitle(task)}</strong>
                        <small>
                          {taskWorker(task)}
                          {taskProxy.badgeLabel ? ` · ${taskProxy.badgeLabel}` : ''} · {taskDuration(task)}
                        </small>
                      </span>
                      <b>{percent}%</b>
                    </button>
                  );
                })}
              </section>
            ))
          )}

          {!isStreaming && hasMoreTasks ? (
            <div className="jdm-runbook-load-more">
              <button
                type="button"
                className="btn btn-secondary"
                disabled={isLoadingMoreTasks}
                onClick={onLoadMoreTasks}
              >
                {isLoadingMoreTasks ? 'Loading more…' : 'Load more tasks'}
              </button>
            </div>
          ) : null}
        </nav>

        <main className="jdm-runbook-focus" aria-label="Selected task detail">
          {selectedTask ? (
            <>
              <div className="jdm-runbook-focus-top">
                <span>Current step · {RUNBOOK_STAGES.find((stage) => stage.id === taskStage(selectedTask))?.label}</span>
                <span className={`jdm-runbook-state jdm-runbook-state-${taskStatusTone(selectedTask.status)}`}>
                  <i aria-hidden="true" />
                  {selectedTask.status.replace(/_/g, ' ')}
                </span>
              </div>
              <h3>{taskTitle(selectedTask)}</h3>
              <p>{taskMessage(selectedTask)}</p>
              <TaskEvidencePages jobId={jobId} task={selectedTask} />
              <div className="jdm-runbook-progress-row">
                <div
                  className="jdm-runbook-progress-track"
                  role="progressbar"
                  aria-label={`${taskTitle(selectedTask)} progress`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={selectedProgress}
                >
                  <span
                    className={`jdm-runbook-progress-fill jdm-runbook-progress-fill-${taskStatusTone(selectedTask.status)}`}
                    style={{ width: `${selectedProgress}%` }}
                  />
                </div>
                <strong>{selectedProgress}%</strong>
              </div>

              <div className="jdm-runbook-numbers">
                <div>
                  <span>Items</span>
                  <strong>{selectedTask.items_processed.toLocaleString()}</strong>
                  <small>of {selectedTask.items_total?.toLocaleString() ?? 'unknown'}</small>
                </div>
                <div>
                  <span>Speed</span>
                  <strong>{formatRate(speedBps)}</strong>
                  <small>{speedBps ? 'live average' : 'not reported'}</small>
                </div>
                <div>
                  <span>Worker</span>
                  <strong>{selectedLiveTransfer?.workerId || workerId || taskWorker(selectedTask)}</strong>
                  <small>
                    attempt {taskAttempt(selectedTask).current} / {taskAttempt(selectedTask).maximum}
                  </small>
                </div>
                <div>
                  <span>Proxy</span>
                  <strong>
                    {selectedProxySummary?.flagEmoji ? `${selectedProxySummary.flagEmoji} ` : ''}
                    {selectedProxySummary?.activeHop?.is_direct
                      ? 'Direct'
                      : selectedProxySummary?.activeHop?.country ||
                        selectedProxySummary?.activeHop?.group ||
                        formatProxyHost(selectedProxySummary?.activeHop?.url)}
                  </strong>
                  <small>
                    {selectedProxySummary?.hasHops
                      ? selectedProxySummary.hopCount > 1
                        ? `Hop ${selectedProxySummary.usedHopNumber || 1} of ${selectedProxySummary.hopCount}`
                        : 'Primary route'
                      : 'No proxy assigned'}
                  </small>
                </div>
              </div>

              {selectedProxySummary && selectedProxySummary.hasHops && (
                <section
                  className="jdm-runbook-routes"
                  aria-label="Configured proxy routes and hop fallback sequence"
                >
                  <header className="jdm-runbook-routes-heading">
                    <div>
                      <span>Proxy Route Sequence</span>
                      <strong>
                        {selectedProxySummary.hopCount === 1
                          ? '1 Configured Route'
                          : `${selectedProxySummary.hopCount} Hops Evaluated in Order`}
                      </strong>
                    </div>
                    <div className="jdm-runbook-routes-summary">
                      {selectedProxySummary.activeHop && (
                        <span className={`jdm-route-status is-${selectedProxySummary.activeHop.status}`}>
                          <i aria-hidden="true" />
                          {selectedProxySummary.activeHop.status === 'used'
                            ? `Resolved Hop ${selectedProxySummary.usedHopNumber}`
                            : selectedProxySummary.activeHop.status === 'failed'
                              ? 'All Hops Failed'
                              : 'Evaluating Route'}
                        </span>
                      )}
                    </div>
                  </header>

                  <div className="jdm-runbook-routes-chain">
                    {selectedProxySummary.hops.map((hop, idx) => (
                      <div
                        key={hop.hop_number}
                        className={`jdm-route-hop-card is-${hop.status} ${hop.is_direct ? 'is-direct' : ''}`}
                      >
                        <div className="jdm-route-hop-header">
                          <span className="jdm-route-hop-step">Hop {hop.hop_number}</span>
                          <span className={`jdm-route-hop-pill is-${hop.status}`}>
                            <i aria-hidden="true" />
                            {hop.status}
                          </span>
                        </div>
                        <div className="jdm-route-hop-title">
                          <span className="jdm-route-hop-role">{hop.role_label}</span>
                          {hop.flag_emoji && (
                            <span className="jdm-route-hop-flag">{hop.flag_emoji}</span>
                          )}
                        </div>
                        <div className="jdm-route-hop-endpoint" title={hop.masked_url}>
                          {hop.is_direct ? 'Direct Connection' : formatProxyHost(hop.url)}
                        </div>
                        <div className="jdm-route-hop-meta">
                          {hop.country ? <span>{hop.country}</span> : null}
                          {hop.group ? <span className="jdm-route-hop-group">{hop.group}</span> : null}
                        </div>
                        {idx < selectedProxySummary.hops.length - 1 && (
                          <div className="jdm-route-hop-arrow" aria-hidden="true">→</div>
                        )}
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {taskStage(selectedTask) === 'download' ? (
                <section
                  className="jdm-runbook-media"
                  aria-label={`Media transfers inside ${taskTitle(selectedTask)}`}
                >
                  <header className="jdm-runbook-media-heading">
                    <div>
                      <span>Files in this pipeline task</span>
                      <strong>{taskTitle(selectedTask)}</strong>
                    </div>
                    <div className="jdm-runbook-media-summary">
                      <strong>{mediaEntries.length} file{mediaEntries.length === 1 ? '' : 's'}</strong>
                      {activeMediaCount > 0 ? <span>{activeMediaCount} active</span> : null}
                      {queuedMediaCount > 0 ? <span>{queuedMediaCount} queued</span> : null}
                      {completeMediaCount > 0 ? <span>{completeMediaCount} complete</span> : null}
                    </div>
                  </header>

                  {selectedMedia ? (
                    <div className="jdm-runbook-current-media" aria-label="Selected file transfer">
                      <MediaPreview entry={selectedMedia} task={selectedTask} jobId={jobId} />
                      <div className="jdm-runbook-current-media-main">
                        <div>
                          <span className={`jdm-runbook-transfer-state is-${selectedMediaState}`}>
                            <i aria-hidden="true" />
                            {selectedMediaState}
                          </span>
                          <strong>{selectedMediaPercent}%</strong>
                        </div>
                        <h5>
                          {fileName(selectedMedia.path || selectedMedia.url) ||
                            `Media ${selectedMedia.mediaId || 'file'}`}
                        </h5>
                        <span>
                          {selectedTask.content_type || 'All media'}
                          {selectedMedia.mediaId ? ` · #${selectedMedia.mediaId}` : ''}
                        </span>
                        <div
                          className="jdm-runbook-media-progress"
                          role="progressbar"
                          aria-label={`${fileName(selectedMedia.path || selectedMedia.url) || 'Media'} transfer progress`}
                          aria-valuemin={0}
                          aria-valuemax={100}
                          aria-valuenow={selectedMediaPercent}
                        >
                          <span style={{ width: `${selectedMediaPercent}%` }} />
                        </div>
                        <div className="jdm-runbook-media-metrics">
                          <span>
                            <b>{formatTransferBytes(selectedMedia.processedBytes)}</b> / {formatTransferBytes(selectedMedia.expectedBytes)}
                          </span>
                          <span><b>{formatRate(selectedMedia.speedBps)}</b></span>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <p className="jdm-runbook-media-empty">
                      Transfer telemetry will appear when the worker reports the first media event.
                    </p>
                  )}

                  {mediaEntries.length > 0 ? (
                    <div
                      className="jdm-runbook-media-results"
                      aria-label={`Files produced by ${taskTitle(selectedTask)}`}
                    >
                      {mediaEntries.slice(0, 6).map((entry) => {
                        const percent = mediaProgress(entry);
                        const state = normalizedMediaState(entry.status, entry.isLive);
                        const filename = fileName(entry.path || entry.url) || `Media ${entry.mediaId || 'file'}`;
                        return (
                          <button
                            type="button"
                            key={entry.key}
                            className={selectedMedia?.key === entry.key ? 'is-selected' : ''}
                            onClick={() => setSelectedMediaKey(entry.key)}
                            aria-label={`${filename}, ${state}, ${percent} percent`}
                          >
                            <MediaPreview entry={entry} task={selectedTask} jobId={jobId} compact />
                            <span className="jdm-runbook-media-result-body">
                              <span>
                                <span className={`jdm-runbook-transfer-state is-${state}`}>
                                  <i aria-hidden="true" />
                                  {state}
                                </span>
                                <b>{percent}%</b>
                              </span>
                              <strong>{filename}</strong>
                              <small>
                                {formatTransferBytes(entry.processedBytes)} / {formatTransferBytes(entry.expectedBytes)} · {formatRate(entry.speedBps)}
                              </small>
                              <span className="jdm-runbook-media-progress" aria-hidden="true">
                                <span style={{ width: `${percent}%` }} />
                              </span>
                            </span>
                          </button>
                        );
                      })}
                      {mediaEntries.length > 6 ? (
                        <small className="jdm-runbook-media-more">
                          +{mediaEntries.length - 6} more media results retained on this task
                        </small>
                      ) : null}
                    </div>
                  ) : null}

                  {selectedMedia ? (
                    <div className="jdm-runbook-media-event">
                      <span>
                        <b>Latest event</b>
                        <code>
                          {selectedMedia.isLive
                            ? `${selectedMedia.status} · ${formatTransferBytes(selectedMedia.processedBytes)} written`
                            : `${selectedMedia.status} · media ${selectedMedia.mediaId || 'unknown'}`}
                        </code>
                      </span>
                      <span>
                        <b>Destination</b>
                        <code>{selectedMedia.path || selectedMedia.url || 'Destination not published'}</code>
                      </span>
                    </div>
                  ) : null}
                  {selectedMedia ? (
                    <div className="jdm-runbook-transfer-segments" aria-label="Transfer chunks">
                      {Array.from({ length: 12 }, (_, index) => {
                        const segmentPercent = ((index + 1) / 12) * 100;
                        return (
                          <span
                            key={index}
                            className={
                              segmentPercent <= selectedMediaPercent
                                ? 'is-complete'
                                : segmentPercent <= selectedMediaPercent + 8.34
                                  ? 'is-active'
                                  : ''
                            }
                          />
                        );
                      })}
                    </div>
                  ) : null}
                  {selectedMedia ? (
                    <div className="jdm-runbook-media-actions">
                      <button
                        type="button"
                        className="btn btn-secondary"
                        disabled={!selectedMedia.path}
                        onClick={() => {
                          if (selectedMedia.path) void copyText(selectedMedia.path);
                        }}
                      >
                        Copy path
                      </button>
                      {selectedMediaUrl ? (
                        <a className="btn btn-primary" href={selectedMediaUrl} target="_blank" rel="noreferrer">
                          Open media
                        </a>
                      ) : null}
                    </div>
                  ) : null}
                </section>
              ) : null}

              {selectedTask.error ? (
                <div className="jdm-runbook-decision">
                  <span>Action required</span>
                  <strong>{selectedTask.error}</strong>
                  <small>
                    {selectedDownloadErrors > 0
                      ? `${selectedDownloadErrors} media transfer${selectedDownloadErrors === 1 ? '' : 's'} failed in this task.`
                      : 'Review the Errors tab for retained task diagnostics.'}
                  </small>
                </div>
              ) : (
                <div className="jdm-runbook-log">
                  <span>Latest task event</span>
                  <code>{taskMessage(selectedTask)}</code>
                </div>
              )}

              <div className="jdm-runbook-dependencies">
                <span>Waits for</span>
                {dependencies.length ? (
                  dependencies.map((dependency) => <code key={dependency}>{dependency}</code>)
                ) : (
                  <em>No dependency data published</em>
                )}
              </div>
              {notices}
            </>
          ) : (
            <div className="jdm-empty">{emptyMessage}</div>
          )}
        </main>

        <aside className="jdm-runbook-summary" aria-label="Run summary">
          <span className="jdm-runbook-eyebrow">Run summary</span>
          <div className="jdm-runbook-summary-state">
            <strong>{terminalCount.toLocaleString()}</strong>
            <span>of {totalCount.toLocaleString()} terminal tasks</span>
          </div>
          {isLiveJob && jobEta?.formattedRemaining ? (
            <div className="jdm-runbook-summary-eta">
              <span className="jdm-runbook-summary-eta-label">Job ETA</span>
              <strong className="jdm-runbook-summary-eta-val">~{jobEta.formattedRemaining}</strong>
            </div>
          ) : null}
          <dl>
            <div><dt>Running</dt><dd>{runningCount}</dd></div>
            <div><dt>Ready</dt><dd>{readyCount}</dd></div>
            <div><dt>Blocked</dt><dd>{blockedCount}</dd></div>
            <div><dt>Deferred</dt><dd>{deferredCount}</dd></div>
            <div><dt>Failed</dt><dd>{failedCount}</dd></div>
          </dl>
          <div className="jdm-runbook-checkpoint">
            <span>Selected checkpoint</span>
            <strong>{selectedTask ? taskTitle(selectedTask) : 'No task selected'}</strong>
            <small>{selectedTask ? `${selectedTask.status.replace(/_/g, ' ')} · ${selectedProgress}%` : 'Waiting for tasks'}</small>
          </div>
          {actions ? <div className="jdm-runbook-summary-actions">{actions}</div> : null}
        </aside>
      </div>
    </div>
  );
}
