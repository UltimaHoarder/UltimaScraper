import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';

import type { Job } from '../../../api/types/jobs';
import { WorkspacePageHeader } from '../../../shared/ui/WorkspacePageHeader';
import {
  getJobPreparationProgress,
  getScheduleLabel,
  resolveEffectiveJobStatus,
  taskTypeLabel,
  timeAgo,
} from '../lib/jobUtils';
import './JobsOperationsLedger.css';

type LedgerSort = 'created' | 'priority' | 'progress';
type SortDirection = 'asc' | 'desc';
type ScheduleFilter = 'all' | 'scheduled' | 'manual';
type OptionalColumn =
  | 'owner'
  | 'type'
  | 'target'
  | 'priority'
  | 'progress'
  | 'workers'
  | 'success'
  | 'errors'
  | 'schedule';

interface JobsOperationsLedgerProps {
  jobs: Job[];
  showApiCommands?: boolean;
  onShowApiCommandsChange?: (value: boolean) => void;
  total: number;
  page: number;
  pageSize: number;
  statusFilter: string;
  searchQuery: string;
  selectedJobId?: string | null;
  isLoading?: boolean;
  isFetching?: boolean;
  isMutating?: boolean;
  onSearchChange: (value: string) => void;
  onStatusFilterChange: (value: string) => void;
  onPageChange: (page: number) => void;
  onPageSizeChange: (pageSize: number) => void;
  onJobClick: (job: Job) => void;
  onPrioritizeJobs: (jobIds: string[]) => void;
  onRetryJobs: (jobIds: string[]) => void;
  onPauseResumeJob?: (jobId: string, action: 'pause' | 'resume') => void;
  onRequestCancelJobs: (jobIds: string[]) => void;
  onRequestDeleteJobs: (jobIds: string[]) => void;
  ownerFilter?: string;
  onOwnerFilterChange?: (value: string) => void;
  typeFilter?: string;
  onTypeFilterChange?: (value: string) => void;
  scheduleFilter?: ScheduleFilter;
  onScheduleFilterChange?: (value: ScheduleFilter) => void;
  availableTypes?: string[];
  availableOwners?: string[];
  onRequestDeleteOlderThan: (hours: number) => void;
  onNewJob: () => void;
  onNotice: (message: string) => void;
}

const STATUS_OPTIONS = [
  { key: 'all', label: 'All' },
  { key: 'running', label: 'Running' },
  { key: 'pending', label: 'Queued' },
  { key: 'failed', label: 'Failed' },
  { key: 'completed', label: 'Completed' },
  { key: 'cancelled', label: 'Cancelled' },
  { key: 'deleting', label: 'Deleting' },
] as const;

const OPTIONAL_COLUMNS: Array<{ key: OptionalColumn; label: string }> = [
  { key: 'owner', label: 'Owner' },
  { key: 'type', label: 'Type' },
  { key: 'target', label: 'Target' },
  { key: 'priority', label: 'Priority' },
  { key: 'progress', label: 'Progress' },
  { key: 'workers', label: 'Workers' },
  { key: 'success', label: 'Success' },
  { key: 'errors', label: 'Errors' },
  { key: 'schedule', label: 'Schedule' },
];

const DEFAULT_COLUMNS = new Set<OptionalColumn>(OPTIONAL_COLUMNS.map(({ key }) => key));

const DELETE_AGE_OPTIONS = [
  { hours: 24, label: 'Older than 24 hours', detail: 'Remove jobs created before yesterday' },
  { hours: 24 * 7, label: 'Older than 7 days', detail: 'Remove jobs created before last week' },
  { hours: 24 * 30, label: 'Older than 30 days', detail: 'Remove jobs created before last month' },
  { hours: 24 * 90, label: 'Older than 90 days', detail: 'Remove jobs created before last quarter' },
] as const;

function isScheduled(job: Job): boolean {
  return Boolean(job.is_scheduled || job.scheduled_for || job.interval_seconds || job.cron);
}

function jobStats(job: Job) {
  const total = job.task_stats?.total ?? job.task_count ?? 0;
  const completed = job.task_stats?.completed ?? job.completed_tasks ?? 0;
  const failed = job.task_stats?.failed ?? job.failed_tasks ?? 0;
  const active = job.task_stats?.inflight ?? 0;
  const terminal = Math.min(total || completed + failed, completed + failed);
  const preparation = job.status === 'deleting' ? null : getJobPreparationProgress(job);
  const progress = job.status === 'deleting'
    ? Math.min(99, Math.round(((job.deletion_progress?.completed_stages ?? 0) / (job.deletion_progress?.total_stages ?? 10)) * 100))
    : preparation
    ? preparation.percent
    : total > 0
      ? Math.min(100, Math.round((terminal / total) * 100))
      : job.status === 'completed'
        ? 100
        : 0;
  const success = terminal > 0 ? (completed / terminal) * 100 : null;
  const errors = Math.max(job.error_stats?.total ?? 0, failed);
  const effectiveStatus = resolveEffectiveJobStatus(job.status, job.task_stats, progress);

  return { total, completed, failed, active, terminal, progress, success, errors, effectiveStatus };
}

function primaryTaskType(job: Job): string {
  if (job.job_type) return taskTypeLabel(job.job_type);
  const typeCounts = Object.entries(job.task_stats?.task_type_counts ?? {});
  if (typeCounts.length > 0) {
    typeCounts.sort((left, right) => right[1] - left[1]);
    const [taskType, count] = typeCounts[0];
    const remainder = Math.max(0, typeCounts.length - 1);
    return `${taskTypeLabel(taskType)}${remainder > 0 ? ` +${remainder}` : ''}${count > 1 ? ` · ${count}` : ''}`;
  }
  return 'General job';
}

function compactTaskCount(count: number): string {
  const compact = (value: number) => value.toFixed(1).replace(/\.0$/, '');
  if (count >= 1_000_000) return `${compact(count / 1_000_000)}m`;
  if (count >= 1_000) return `${compact(count / 1_000)}k`;
  return count.toLocaleString();
}

function jobTarget(job: Job): { label: string; detail: string; compactDetail: string } {
  const usernames = Array.from(
    new Set((job.tasks ?? []).map((task) => task.username).filter((value): value is string => Boolean(value)))
  );
  const stats = jobStats(job);
  const taskLabel = stats.total === 1 ? 'task' : 'tasks';
  const detail = `${stats.total.toLocaleString()} ${taskLabel}`;
  const compactDetail = compactTaskCount(stats.total);
  if (usernames.length > 0) {
    return {
      label: `@${usernames[0].replace(/^@/, '')}${usernames.length > 1 ? ` +${usernames.length - 1}` : ''}`,
      detail,
      compactDetail,
    };
  }
  const siteKey = job.site?.trim().toLowerCase().replace(/[-_\s]/g, '');
  const knownSites: Record<string, string> = {
    fansly: 'Fansly',
    loyalfans: 'LoyalFans',
    onlyfans: 'OnlyFans',
  };
  return {
    label: siteKey
      ? knownSites[siteKey] ?? job.site!.replace(/(^|[-_])([a-z])/g, (_match, lead: string, char: string) => `${lead ? ' ' : ''}${char.toUpperCase()}`)
      : 'Cross-site',
    detail,
    compactDetail,
  };
}

function priorityDetails(job: Job): { label: string; tone: string; rank: number } {
  const priority = Number(job.priority ?? 0);
  if (priority < 0) return { label: 'Front', tone: 'front', rank: 3 };
  if (priority === 0) return { label: 'Standard', tone: 'standard', rank: 2 };
  return { label: `P${priority}`, tone: 'deferred', rank: 1 };
}

function jobCreatedLabel(job: Job): { primary: string; secondary: string; title: string } {
  const parsed = new Date(job.created_at);
  if (Number.isNaN(parsed.getTime())) {
    return { primary: job.created_at || '—', secondary: 'unknown time', title: job.created_at || '' };
  }
  return {
    primary: parsed.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    secondary: timeAgo(job.created_at),
    title: parsed.toLocaleString(),
  };
}

function formatSuccess(value: number | null): string {
  if (value === null) return '—';
  if (value >= 99.95) return '100%';
  return `${value.toFixed(value >= 99 ? 1 : 0)}%`;
}

function pageNumbers(page: number, pageCount: number): Array<number | 'ellipsis'> {
  const numbers = Array.from(
    new Set([1, page - 1, page, page + 1, pageCount].filter((value) => value >= 1 && value <= pageCount))
  ).sort((left, right) => left - right);
  const result: Array<number | 'ellipsis'> = [];
  numbers.forEach((value, index) => {
    if (index > 0 && value - numbers[index - 1] > 1) result.push('ellipsis');
    result.push(value);
  });
  return result;
}

export function JobsOperationsLedger({
  jobs,
  showApiCommands = false,
  onShowApiCommandsChange,
  total,
  page,
  pageSize,
  statusFilter,
  searchQuery,
  selectedJobId,
  isLoading = false,
  isFetching = false,
  isMutating = false,
  onSearchChange,
  onStatusFilterChange,
  onPageChange,
  onPageSizeChange,
  onJobClick,
  onPrioritizeJobs,
  onRetryJobs,
  onPauseResumeJob,
  onRequestCancelJobs,
  onRequestDeleteJobs,
  ownerFilter: propOwnerFilter,
  onOwnerFilterChange,
  typeFilter: propTypeFilter,
  onTypeFilterChange,
  scheduleFilter: propScheduleFilter,
  onScheduleFilterChange,
  availableTypes,
  availableOwners,
  onRequestDeleteOlderThan,
  onNewJob,
  onNotice,
}: JobsOperationsLedgerProps) {
  const [sort, setSort] = useState<LedgerSort>('created');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [localOwnerFilter, setLocalOwnerFilter] = useState('all');
  const [localTypeFilter, setLocalTypeFilter] = useState('all');
  const [localScheduleFilter, setLocalScheduleFilter] = useState<ScheduleFilter>('all');
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [utilityMenu, setUtilityMenu] = useState<'views' | 'columns' | 'deletion' | null>(null);
  const [rowMenu, setRowMenu] = useState<{
    jobId: string;
    top: number;
    left: number;
    flipUp: boolean;
  } | null>(null);
  const [visibleColumns, setVisibleColumns] = useState<Set<OptionalColumn>>(
    () => new Set(DEFAULT_COLUMNS)
  );

  const handleToggleRowMenu = (jobId: string, buttonEl: HTMLButtonElement) => {
    if (rowMenu?.jobId === jobId) {
      setRowMenu(null);
      return;
    }
    const rect = buttonEl.getBoundingClientRect();
    const estimatedMenuHeight = 170;
    const flipUp = rect.bottom + estimatedMenuHeight > window.innerHeight;
    setRowMenu({
      jobId,
      top: flipUp ? rect.top : rect.bottom + 4,
      left: rect.right,
      flipUp,
    });
  };

  const ownerFilter = propOwnerFilter !== undefined ? propOwnerFilter : localOwnerFilter;
  const setOwnerFilter = (value: string) => {
    if (onOwnerFilterChange) onOwnerFilterChange(value);
    else setLocalOwnerFilter(value);
  };

  const typeFilter = propTypeFilter !== undefined ? propTypeFilter : localTypeFilter;
  const setTypeFilter = (value: string) => {
    if (onTypeFilterChange) onTypeFilterChange(value);
    else setLocalTypeFilter(value);
  };

  const scheduleFilter = propScheduleFilter !== undefined ? propScheduleFilter : localScheduleFilter;
  const setScheduleFilter = (value: ScheduleFilter) => {
    if (onScheduleFilterChange) onScheduleFilterChange(value);
    else setLocalScheduleFilter(value);
  };

  const owners = useMemo(() => {
    const list = new Set<string>(availableOwners ?? []);
    jobs.forEach((job) => list.add(job.created_by || 'system'));
    if (ownerFilter && ownerFilter !== 'all') list.add(ownerFilter);
    return Array.from(list).sort();
  }, [availableOwners, jobs, ownerFilter]);

  const types = useMemo(() => {
    const list = new Set<string>();
    (availableTypes ?? []).forEach((t) => list.add(taskTypeLabel(t)));
    jobs.forEach((job) => list.add(primaryTaskType(job)));
    if (typeFilter && typeFilter !== 'all') list.add(typeFilter);
    return Array.from(list).sort();
  }, [availableTypes, jobs, typeFilter]);

  const isServerFiltered = Boolean(onTypeFilterChange || onOwnerFilterChange || onScheduleFilterChange);

  const visibleJobs = useMemo(() => {
    const locallyFiltered = isServerFiltered
      ? jobs
      : jobs.filter((job) => {
          if (ownerFilter !== 'all' && (job.created_by || 'system') !== ownerFilter) return false;
          if (typeFilter !== 'all' && primaryTaskType(job) !== typeFilter) return false;
          if (scheduleFilter === 'scheduled' && !isScheduled(job)) return false;
          if (scheduleFilter === 'manual' && isScheduled(job)) return false;
          return true;
        });

    return [...locallyFiltered].sort((left, right) => {
      let comparison = 0;
      if (sort === 'created') {
        comparison = new Date(left.created_at).getTime() - new Date(right.created_at).getTime();
      } else if (sort === 'priority') {
        comparison = priorityDetails(left).rank - priorityDetails(right).rank;
      } else {
        comparison = jobStats(left).progress - jobStats(right).progress;
      }
      return sortDirection === 'asc' ? comparison : -comparison;
    });
  }, [isServerFiltered, jobs, ownerFilter, scheduleFilter, sort, sortDirection, typeFilter]);

  useEffect(() => {
    const loadedIds = new Set(jobs.map((job) => job.job_id));
    setSelected((current) => {
      const next = new Set(Array.from(current).filter((jobId) => loadedIds.has(jobId)));
      if (next.size === current.size) return current;
      return next;
    });
  }, [jobs]);

  useEffect(() => {
    const handleOutsideClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (!target) return;
      if (
        target.closest('.jobs-ledger-popover-anchor') ||
        target.closest('.jobs-ledger-row-actions') ||
        target.closest('.jobs-ledger-row-dropdown')
      ) {
        return;
      }
      setUtilityMenu(null);
      setRowMenu(null);
      setFiltersOpen(false);
    };

    const closeMenus = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setUtilityMenu(null);
      setRowMenu(null);
      setFiltersOpen(false);
    };

    const handleScrollOrResize = () => {
      setRowMenu(null);
    };

    window.addEventListener('keydown', closeMenus);
    document.addEventListener('mousedown', handleOutsideClick);
    window.addEventListener('scroll', handleScrollOrResize, true);
    window.addEventListener('resize', handleScrollOrResize);
    return () => {
      window.removeEventListener('keydown', closeMenus);
      document.removeEventListener('mousedown', handleOutsideClick);
      window.removeEventListener('scroll', handleScrollOrResize, true);
      window.removeEventListener('resize', handleScrollOrResize);
    };
  }, []);

  const selectedJobs = jobs.filter((job) => selected.has(job.job_id));
  const selectedActiveIds = selectedJobs
    .filter((job) => job.status === 'running' || job.status === 'pending')
    .map((job) => job.job_id);
  const selectedFailedIds = selectedJobs
    .filter((job) => job.status === 'failed')
    .map((job) => job.job_id);
  const allVisibleSelected = visibleJobs.length > 0 && visibleJobs.every((job) => selected.has(job.job_id));
  const activeFilterCount = Number(ownerFilter !== 'all') + Number(typeFilter !== 'all') + Number(scheduleFilter !== 'all');
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const firstVisible = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const lastVisible = Math.min(total, firstVisible + (isServerFiltered ? jobs.length : visibleJobs.length) - 1);
  const hasLocalFilters = !isServerFiltered && activeFilterCount > 0;
  const activeMenuJob = rowMenu ? visibleJobs.find((job) => job.job_id === rowMenu.jobId) ?? null : null;
  const activeMenuStats = activeMenuJob ? jobStats(activeMenuJob) : null;
  const canControlActive =
    activeMenuStats?.effectiveStatus === 'running' || activeMenuStats?.effectiveStatus === 'pending';
  // Only ledger runs can pause; the backend rejects pause for other engines.
  const pauseResumeAction = onPauseResumeJob && activeMenuJob?.execution_engine === 'ledger'
    ? activeMenuJob.status === 'paused' ? 'resume' : canControlActive ? 'pause' : null
    : null;

  const toggleSort = (nextSort: LedgerSort) => {
    if (sort === nextSort) {
      setSortDirection((current) => current === 'desc' ? 'asc' : 'desc');
      return;
    }
    setSort(nextSort);
    setSortDirection('desc');
  };

  const toggleSelection = (jobId: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(jobId)) next.delete(jobId);
      else next.add(jobId);
      return next;
    });
  };

  const toggleVisibleSelection = () => {
    setSelected((current) => {
      const next = new Set(current);
      if (allVisibleSelected) visibleJobs.forEach((job) => next.delete(job.job_id));
      else visibleJobs.forEach((job) => next.add(job.job_id));
      return next;
    });
  };

  const toggleColumn = (column: OptionalColumn) => {
    setVisibleColumns((current) => {
      const next = new Set(current);
      if (next.has(column)) next.delete(column);
      else next.add(column);
      return next;
    });
  };

  const selectSavedView = (status: string) => {
    onStatusFilterChange(status);
    setOwnerFilter('all');
    setTypeFilter('all');
    setScheduleFilter('all');
    setUtilityMenu(null);
  };

  const copySelectedIds = async () => {
    try {
      if (!navigator.clipboard) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(selectedJobs.map((job) => job.job_id).join('\n'));
      onNotice(`Copied ${selectedJobs.length} job ${selectedJobs.length === 1 ? 'ID' : 'IDs'}.`);
    } catch {
      onNotice('Clipboard access is unavailable in this browser.');
    }
  };

  const columnVisible = (column: OptionalColumn) => visibleColumns.has(column);
  const columnCount = visibleColumns.size + 5;

  return (
    <section className="jobs-ledger" aria-label="Operations ledger">
      <WorkspacePageHeader
        eyebrow="Jobs"
        title="Operations ledger"
        subtitle={`${total.toLocaleString()} matching jobs · High-density queue and history management`}
        icon="◇"
        meta={(
          <div className="jobs-ledger-header-actions">
          <div className="jobs-ledger-popover-anchor">
            <button
              type="button"
              className="jobs-ledger-button"
              aria-expanded={utilityMenu === 'views'}
              aria-controls="jobs-ledger-saved-views"
              onClick={() => setUtilityMenu((current) => current === 'views' ? null : 'views')}
            >
              Saved views <span aria-hidden="true">⌄</span>
            </button>
            {utilityMenu === 'views' ? (
              <div id="jobs-ledger-saved-views" className="jobs-ledger-popover" role="menu">
                <span>Queue views</span>
                {STATUS_OPTIONS.map((option) => (
                  <button
                    type="button"
                    role="menuitem"
                    key={option.key}
                    className={statusFilter === option.key ? 'is-active' : ''}
                    onClick={() => selectSavedView(option.key)}
                  >
                    <span>{option.label}</span>
                    <small>{option.key === 'all' ? 'Complete history' : `${option.label} jobs only`}</small>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <div className="jobs-ledger-popover-anchor">
            <button
              type="button"
              className="jobs-ledger-button jobs-ledger-delete-button"
              aria-expanded={utilityMenu === 'deletion'}
              aria-controls="jobs-ledger-delete-options"
              onClick={() => setUtilityMenu((current) => current === 'deletion' ? null : 'deletion')}
            >
              Delete jobs <span aria-hidden="true">⌄</span>
            </button>
            {utilityMenu === 'deletion' ? (
              <div id="jobs-ledger-delete-options" className="jobs-ledger-popover" role="menu">
                <span>Cleanup options</span>
                <button
                  type="button"
                  role="menuitem"
                  disabled={selectedJobs.length === 0 || isMutating}
                  onClick={() => {
                    setUtilityMenu(null);
                    onRequestDeleteJobs(selectedJobs.map((job) => job.job_id));
                  }}
                >
                  <span>Delete selected</span>
                  <small>{selectedJobs.length > 0 ? `${selectedJobs.length} selected jobs` : 'Select jobs in the ledger first'}</small>
                </button>
                {DELETE_AGE_OPTIONS.map((option) => (
                  <button
                    type="button"
                    role="menuitem"
                    key={option.hours}
                    disabled={isMutating}
                    onClick={() => {
                      setUtilityMenu(null);
                      onRequestDeleteOlderThan(option.hours);
                    }}
                  >
                    <span>{option.label}</span>
                    <small>{option.detail}</small>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <button type="button" className="jobs-ledger-new" onClick={onNewJob}>
            <span aria-hidden="true">＋</span> New job
          </button>
          </div>
        )}
      />

      <div className="jobs-ledger-toolbar">
        <label className="jobs-ledger-search">
          <span aria-hidden="true">⌕</span>
          <input
            type="search"
            aria-label="Search operations ledger"
            placeholder="Search job, ID, target, owner…"
            value={searchQuery}
            onChange={(event) => onSearchChange(event.target.value)}
          />
        </label>
        <div className="jobs-ledger-statuses" role="group" aria-label="Job status filter">
          {STATUS_OPTIONS.map((option) => (
            <button
              type="button"
              key={option.key}
              aria-pressed={statusFilter === option.key}
              className={statusFilter === option.key ? 'is-active' : ''}
              onClick={() => onStatusFilterChange(option.key)}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className="jobs-ledger-popover-anchor">
          <button
            type="button"
            className={`jobs-ledger-tool ${filtersOpen ? 'is-active' : ''} ${activeFilterCount > 0 ? 'has-active-filters' : ''}`}
            aria-expanded={filtersOpen}
            aria-controls="jobs-ledger-advanced-filters"
            onClick={() => {
              setFiltersOpen((current) => !current);
              setUtilityMenu(null);
            }}
          >
            Filters {activeFilterCount > 0 ? <b>{activeFilterCount}</b> : null}
          </button>
          {filtersOpen ? (
            <div
              id="jobs-ledger-advanced-filters"
              className="jobs-ledger-popover jobs-ledger-filters-popover"
              role="region"
              aria-label="Advanced filters"
            >
              <div className="jobs-ledger-filters-popover-header">
                <div>
                  <span>Advanced filters</span>
                  <small>{isServerFiltered ? 'Filter across all server jobs.' : 'These refine the currently loaded server result.'}</small>
                </div>
                <button
                  type="button"
                  className="jobs-ledger-filters-clear-btn"
                  onClick={() => {
                    setOwnerFilter('all');
                    setTypeFilter('all');
                    setScheduleFilter('all');
                  }}
                  disabled={activeFilterCount === 0}
                >
                  Clear filters
                </button>
              </div>

              <div className="jobs-ledger-filters-popover-body">
                {onShowApiCommandsChange ? (
                  <label className="jobs-ledger-filter-checkbox-label">
                    <input
                      type="checkbox"
                      checked={showApiCommands}
                      onChange={(event) => onShowApiCommandsChange(event.target.checked)}
                    />
                    <span>Show API commands</span>
                  </label>
                ) : null}

                <label className="jobs-ledger-filter-field">
                  <span className="jobs-ledger-filter-label">Owner</span>
                  <select
                    value={ownerFilter}
                    onChange={(event) => setOwnerFilter(event.target.value)}
                  >
                    <option value="all">All owners</option>
                    {owners.map((owner) => (
                      <option key={owner} value={owner}>{owner}</option>
                    ))}
                  </select>
                </label>

                <label className="jobs-ledger-filter-field">
                  <span className="jobs-ledger-filter-label">Type</span>
                  <select
                    value={typeFilter}
                    onChange={(event) => setTypeFilter(event.target.value)}
                  >
                    <option value="all">All types</option>
                    {types.map((type) => (
                      <option key={type} value={type}>{type}</option>
                    ))}
                  </select>
                </label>

                <label className="jobs-ledger-filter-field">
                  <span className="jobs-ledger-filter-label">Schedule</span>
                  <select
                    value={scheduleFilter}
                    onChange={(event) => setScheduleFilter(event.target.value as ScheduleFilter)}
                  >
                    <option value="all">All schedules</option>
                    <option value="scheduled">Scheduled</option>
                    <option value="manual">Manual</option>
                  </select>
                </label>
              </div>
            </div>
          ) : null}
        </div>
        <div className="jobs-ledger-popover-anchor">
          <button
            type="button"
            className="jobs-ledger-tool"
            aria-expanded={utilityMenu === 'columns'}
            aria-controls="jobs-ledger-columns"
            onClick={() => setUtilityMenu((current) => current === 'columns' ? null : 'columns')}
          >
            Columns <b>{columnCount}</b>
          </button>
          {utilityMenu === 'columns' ? (
            <div id="jobs-ledger-columns" className="jobs-ledger-popover jobs-ledger-columns" role="group" aria-label="Visible columns">
              <span>Visible columns</span>
              {OPTIONAL_COLUMNS.map((column) => (
                <label key={column.key}>
                  <input
                    type="checkbox"
                    checked={columnVisible(column.key)}
                    onChange={() => toggleColumn(column.key)}
                  />
                  {column.label}
                </label>
              ))}
            </div>
          ) : null}
        </div>
        <span className={`jobs-ledger-refresh ${isFetching ? 'is-refreshing' : ''}`} role="status">
          <i aria-hidden="true" /> {isFetching ? 'Refreshing' : `${jobs.length.toLocaleString()} loaded`}
        </span>
      </div>

      {activeFilterCount > 0 || (showApiCommands && onShowApiCommandsChange) ? (
        <div className="jobs-ledger-active-filters" role="group" aria-label="Active filters">
          <span className="jobs-ledger-active-filters-label">Active filters:</span>
          {typeFilter !== 'all' ? (
            <button
              type="button"
              className="jobs-ledger-filter-chip"
              onClick={() => setTypeFilter('all')}
              aria-label={`Remove Type: ${typeFilter} filter`}
            >
              <span>Type: <b>{typeFilter}</b></span>
              <span className="jobs-ledger-chip-x" aria-hidden="true">✕</span>
            </button>
          ) : null}
          {ownerFilter !== 'all' ? (
            <button
              type="button"
              className="jobs-ledger-filter-chip"
              onClick={() => setOwnerFilter('all')}
              aria-label={`Remove Owner: ${ownerFilter} filter`}
            >
              <span>Owner: <b>{ownerFilter}</b></span>
              <span className="jobs-ledger-chip-x" aria-hidden="true">✕</span>
            </button>
          ) : null}
          {scheduleFilter !== 'all' ? (
            <button
              type="button"
              className="jobs-ledger-filter-chip"
              onClick={() => setScheduleFilter('all')}
              aria-label={`Remove Schedule: ${scheduleFilter} filter`}
            >
              <span>Schedule: <b>{scheduleFilter}</b></span>
              <span className="jobs-ledger-chip-x" aria-hidden="true">✕</span>
            </button>
          ) : null}
          {showApiCommands && onShowApiCommandsChange ? (
            <button
              type="button"
              className="jobs-ledger-filter-chip"
              onClick={() => onShowApiCommandsChange(false)}
              aria-label="Hide API commands"
            >
              <span>API commands: <b>Visible</b></span>
              <span className="jobs-ledger-chip-x" aria-hidden="true">✕</span>
            </button>
          ) : null}
          <button
            type="button"
            className="jobs-ledger-filter-chip-clear"
            onClick={() => {
              setOwnerFilter('all');
              setTypeFilter('all');
              setScheduleFilter('all');
              if (onShowApiCommandsChange) onShowApiCommandsChange(false);
            }}
          >
            Clear all
          </button>
        </div>
      ) : null}

      {selected.size > 0 ? (
        <div className="jobs-ledger-bulk" role="toolbar" aria-label="Selected jobs actions">
          <strong>{selected.size} {selected.size === 1 ? 'job' : 'jobs'} selected</strong>
          <button
            type="button"
            disabled={selectedActiveIds.length === 0 || isMutating}
            onClick={() => onPrioritizeJobs(selectedActiveIds)}
          >
            Move to front{selectedActiveIds.length > 0 ? ` (${selectedActiveIds.length})` : ''}
          </button>
          <button
            type="button"
            disabled={selectedFailedIds.length === 0 || isMutating}
            onClick={() => onRetryJobs(selectedFailedIds)}
          >
            Retry failed{selectedFailedIds.length > 0 ? ` (${selectedFailedIds.length})` : ''}
          </button>
          <button type="button" disabled={isMutating} onClick={() => void copySelectedIds()}>Copy IDs</button>
          <button
            type="button"
            className="is-danger"
            disabled={selectedActiveIds.length === 0 || isMutating}
            onClick={() => onRequestCancelJobs(selectedActiveIds)}
          >
            Cancel jobs{selectedActiveIds.length > 0 ? ` (${selectedActiveIds.length})` : ''}
          </button>
          <button
            type="button"
            className="is-danger"
            disabled={isMutating}
            onClick={() => onRequestDeleteJobs(selectedJobs.map((job) => job.job_id))}
          >
            Delete jobs ({selectedJobs.length})
          </button>
          <button type="button" className="jobs-ledger-bulk-clear" onClick={() => setSelected(new Set())}>Clear ×</button>
        </div>
      ) : null}

      <div className="jobs-ledger-table-viewport">
        <table className="jobs-ledger-table" aria-label="Jobs operations ledger">
          <thead>
            <tr>
              <th className="jobs-ledger-cell-select">
                <input
                  type="checkbox"
                  aria-label="Select all visible jobs"
                  checked={allVisibleSelected}
                  onChange={toggleVisibleSelection}
                />
              </th>
              <th className="jobs-ledger-cell-created" aria-sort={sort === 'created' ? (sortDirection === 'desc' ? 'descending' : 'ascending') : 'none'}>
                <button type="button" onClick={() => toggleSort('created')}>Created {sort === 'created' ? (sortDirection === 'desc' ? '↓' : '↑') : ''}</button>
              </th>
              <th className="jobs-ledger-cell-status">Status</th>
              <th className="jobs-ledger-cell-job">Job / ID</th>
              {columnVisible('owner') ? <th className="jobs-ledger-cell-owner">Owner</th> : null}
              {columnVisible('type') ? <th className="jobs-ledger-cell-type">Type</th> : null}
              {columnVisible('target') ? <th className="jobs-ledger-cell-target">Target</th> : null}
              {columnVisible('priority') ? (
                <th className="jobs-ledger-cell-priority" aria-sort={sort === 'priority' ? (sortDirection === 'desc' ? 'descending' : 'ascending') : 'none'}>
                  <button type="button" onClick={() => toggleSort('priority')}>Priority {sort === 'priority' ? (sortDirection === 'desc' ? '↓' : '↑') : ''}</button>
                </th>
              ) : null}
              {columnVisible('progress') ? (
                <th className="jobs-ledger-cell-progress" aria-sort={sort === 'progress' ? (sortDirection === 'desc' ? 'descending' : 'ascending') : 'none'}>
                  <button type="button" onClick={() => toggleSort('progress')}>Progress {sort === 'progress' ? (sortDirection === 'desc' ? '↓' : '↑') : ''}</button>
                </th>
              ) : null}
              {columnVisible('workers') ? <th className="jobs-ledger-cell-workers">Workers</th> : null}
              {columnVisible('success') ? <th className="jobs-ledger-cell-success">Success</th> : null}
              {columnVisible('errors') ? <th className="jobs-ledger-cell-errors">Errors</th> : null}
              {columnVisible('schedule') ? <th className="jobs-ledger-cell-schedule">Schedule</th> : null}
              <th className="jobs-ledger-cell-actions"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {visibleJobs.map((job) => {
              const created = jobCreatedLabel(job);
              const stats = jobStats(job);
              const target = jobTarget(job);
              const priority = priorityDetails(job);
              const schedule = getScheduleLabel(job);
              const activity = job.last_activity_at || job.updated_at || job.last_ran_at;
              const preparation = job.status === 'deleting' ? null : getJobPreparationProgress(job);
              const deletionDetail = job.status === 'deleting'
                ? `${job.deletion_progress?.completed_stages ?? 0}/${job.deletion_progress?.total_stages ?? 10} stages · ${(job.deletion_progress?.rows ?? 0).toLocaleString()} rows removed${job.deletion_progress?.partitions_dropped ? ` + ${job.deletion_progress.partitions_dropped} partitions dropped` : ''} · ${job.deletion_progress?.error ? 'Retrying cleanup' : job.deletion_progress?.table ?? 'Queued'}`
                : undefined;
              const statusLabel = preparation
                ? preparation.label
                : stats.effectiveStatus === 'pending'
                  ? 'Queued'
                  : stats.effectiveStatus;
              return (
                <tr
                  key={job.job_id}
                  className={`${stats.effectiveStatus === 'failed' ? 'is-failed' : ''} ${selectedJobId === job.job_id ? 'is-focused' : ''}`}
                >
                  <td className="jobs-ledger-cell-select">
                    <input
                      type="checkbox"
                      aria-label={`Select ${job.job_name || job.job_id}`}
                      checked={selected.has(job.job_id)}
                      onChange={() => toggleSelection(job.job_id)}
                    />
                  </td>
                  <td className="jobs-ledger-cell-created" data-label="Created" title={created.title}><strong>{created.primary}</strong><small>{created.secondary}</small></td>
                  <td className="jobs-ledger-cell-status" data-label="Status"><span className={`jobs-ledger-status is-${stats.effectiveStatus}`}><i aria-hidden="true" />{statusLabel}</span></td>
                  <th scope="row" className="jobs-ledger-cell-job">
                    <button type="button" onClick={() => onJobClick(job)}>
                      <strong>{job.job_name || `Job ${job.job_id}`}</strong>
                      <code>{job.job_id}</code>
                    </button>
                  </th>
                  {columnVisible('owner') ? <td className="jobs-ledger-cell-owner" data-label="Owner">{job.created_by || 'system'}</td> : null}
                  {columnVisible('type') ? <td className="jobs-ledger-cell-type" data-label="Type" title={primaryTaskType(job)}>{primaryTaskType(job)}</td> : null}
                  {columnVisible('target') ? (
                    <td className="jobs-ledger-cell-target" data-label="Target">
                      <strong>{target.label}</strong>
                      <small>
                        <span className="jobs-ledger-target-detail-full">{target.detail}</span>
                        <span
                          className="jobs-ledger-target-detail-compact"
                          title={target.detail}
                        >
                          {target.compactDetail}<span className="sr-only"> tasks</span>
                        </span>
                      </small>
                    </td>
                  ) : null}
                  {columnVisible('priority') ? <td className="jobs-ledger-cell-priority" data-label="Priority"><span className={`jobs-ledger-priority is-${priority.tone}`}>{priority.label}</span></td> : null}
                  {columnVisible('progress') ? (
                    <td className="jobs-ledger-cell-progress" data-label="Progress">
                      <div
                        className={`jobs-ledger-progress is-${stats.effectiveStatus}`}
                        role="progressbar"
                        aria-label={`${job.job_name || job.job_id} progress`}
                        aria-valuemin={0}
                        aria-valuemax={100}
                        aria-valuenow={stats.progress}
                        aria-valuetext={deletionDetail}
                        title={deletionDetail}
                      >
                        <span><i style={{ width: `${stats.progress}%` }} /></span>
                        <b>{job.status === 'deleting' ? `${job.deletion_progress?.completed_stages ?? 0}/${job.deletion_progress?.total_stages ?? 10}` : `${stats.progress}%`}</b>
                      </div>
                    </td>
                  ) : null}
                  {columnVisible('workers') ? (
                    <td className="jobs-ledger-cell-workers is-mono" data-label="Workers" title={job.worker_id || undefined}>
                      {job.worker_id || stats.active || '—'}
                    </td>
                  ) : null}
                  {columnVisible('success') ? (
                    <td className={`jobs-ledger-cell-success is-mono ${stats.success !== null && stats.success < 95 ? 'is-bad' : ''}`} data-label="Success">{formatSuccess(stats.success)}</td>
                  ) : null}
                  {columnVisible('errors') ? <td className={`jobs-ledger-cell-errors is-mono ${stats.errors > 0 ? 'is-bad' : ''}`} data-label="Errors">{stats.errors.toLocaleString()}</td> : null}
                  {columnVisible('schedule') ? (
                    <td className="jobs-ledger-cell-schedule" data-label="Schedule"><strong>{schedule || 'Manual'}</strong><small>{activity ? `updated ${timeAgo(activity)}` : `${job.run_count || 0} runs`}</small></td>
                  ) : null}
                  <td className="jobs-ledger-cell-actions jobs-ledger-row-actions">
                    <button
                      type="button"
                      aria-label={`Actions for ${job.job_name || job.job_id}`}
                      aria-expanded={rowMenu?.jobId === job.job_id}
                      onClick={(event) => handleToggleRowMenu(job.job_id, event.currentTarget)}
                    >
                      •••
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {isLoading ? (
          <div className="jobs-ledger-state" role="status"><i aria-hidden="true" /><strong>Loading jobs</strong><span>Refreshing queue state and recent executions.</span></div>
        ) : visibleJobs.length === 0 ? (
          <div className="jobs-ledger-state"><strong>No jobs in this view</strong><span>Adjust the search or filters, or create a new job.</span><button type="button" onClick={onNewJob}>Create job</button></div>
        ) : null}
      </div>

      <footer className="jobs-ledger-pagination">
        <span>
          {hasLocalFilters
            ? `${visibleJobs.length} of ${jobs.length} loaded rows · ${total.toLocaleString()} server matches`
            : total === 0
              ? '0 matching jobs'
              : `${firstVisible.toLocaleString()}–${lastVisible.toLocaleString()} of ${total.toLocaleString()}`}
        </span>
        <nav aria-label="Jobs pages">
          <button type="button" aria-label="Previous page" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>‹</button>
          {pageNumbers(page, pageCount).map((value, index) => value === 'ellipsis'
            ? <span key={`ellipsis-${index}`}>…</span>
            : (
              <button
                type="button"
                key={value}
                aria-label={`Page ${value}`}
                aria-current={value === page ? 'page' : undefined}
                className={value === page ? 'is-active' : ''}
                onClick={() => onPageChange(value)}
              >
                {value.toLocaleString()}
              </button>
            ))}
          <button type="button" aria-label="Next page" disabled={page >= pageCount} onClick={() => onPageChange(page + 1)}>›</button>
        </nav>
        <label>
          Rows
          <select value={pageSize} onChange={(event) => onPageSizeChange(Number(event.target.value))}>
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
            <option value={200}>200</option>
          </select>
        </label>
      </footer>

      {rowMenu && activeMenuJob ? createPortal(
        <div
          role="menu"
          className="jobs-ledger-row-dropdown"
          style={{
            position: 'fixed',
            top: rowMenu.flipUp ? undefined : `${rowMenu.top}px`,
            bottom: rowMenu.flipUp ? `${Math.max(0, window.innerHeight - rowMenu.top + 4)}px` : undefined,
            right: `${Math.max(8, window.innerWidth - rowMenu.left)}px`,
            zIndex: 1000,
          }}
        >
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setRowMenu(null);
              onJobClick(activeMenuJob);
            }}
          >
            Open details
          </button>
          {canControlActive ? (
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setRowMenu(null);
                onPrioritizeJobs([activeMenuJob.job_id]);
              }}
            >
              Move to front
            </button>
          ) : null}
          {pauseResumeAction ? (
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setRowMenu(null);
                onPauseResumeJob?.(activeMenuJob.job_id, pauseResumeAction);
              }}
            >
              {pauseResumeAction === 'resume' ? 'Resume job' : 'Pause job'}
            </button>
          ) : null}
          {activeMenuJob.status === 'failed' ? (
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setRowMenu(null);
                onRetryJobs([activeMenuJob.job_id]);
              }}
            >
              Retry job
            </button>
          ) : null}
          {canControlActive ? (
            <button
              type="button"
              role="menuitem"
              className="is-danger"
              onClick={() => {
                setRowMenu(null);
                onRequestCancelJobs([activeMenuJob.job_id]);
              }}
            >
              Cancel job
            </button>
          ) : null}
          <button
            type="button"
            role="menuitem"
            className="is-danger"
            onClick={() => {
              setRowMenu(null);
              onRequestDeleteJobs([activeMenuJob.job_id]);
            }}
          >
            Delete job
          </button>
        </div>,
        document.body
      ) : null}
    </section>
  );
}
