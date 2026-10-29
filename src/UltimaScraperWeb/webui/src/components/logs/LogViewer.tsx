import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getWebSocketBaseUrl } from '../../api/http';
import { useWebSocket } from '../../hooks/useWebSocket';
import './LogViewer.css';

export interface LogEntry {
  timestamp: string;
  level: 'debug' | 'info' | 'warning' | 'error';
  message: string;
  source?: string;
  category?: string;
}

export interface LogViewerStats {
  total: number;
  filtered: number;
  errors: number;
  warnings: number;
  info: number;
  debug: number;
  isConnected: boolean;
  isPaused: boolean;
}

export interface LogViewerProps {
  initialLogs?: LogEntry[];
  onStatsChange?: (stats: LogViewerStats) => void;
  className?: string;
}

const MAX_LOG_ENTRIES = 2000;
const MAX_MESSAGE_LENGTH = 4000;
const FLUSH_INTERVAL_MS = 200;

const DEFAULT_CATEGORIES = [
  'jobs',
  'tasks',
  'workers',
  'scraping',
  'downloads',
  'system',
] as const;

function normalizeLevel(raw: unknown): LogEntry['level'] {
  const value = typeof raw === 'string' ? raw.toLowerCase() : 'info';
  if (value === 'debug' || value === 'info' || value === 'warning' || value === 'error') {
    return value;
  }
  return 'info';
}

function normalizeMessage(raw: unknown): string {
  const text = (() => {
    if (typeof raw === 'string') return raw;
    try {
      return JSON.stringify(raw);
    } catch {
      return String(raw);
    }
  })();
  if (text.length <= MAX_MESSAGE_LENGTH) return text;
  const omitted = text.length - MAX_MESSAGE_LENGTH;
  return `${text.slice(0, MAX_MESSAGE_LENGTH)}... [truncated ${omitted} chars]`;
}

function formatTime(iso: string, fullIso = false): string {
  if (fullIso) return iso;
  try {
    const d = new Date(iso);
    const pad = (n: number, z = 2) => String(n).padStart(z, '0');
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;
  } catch {
    return iso;
  }
}

function highlightText(text: string, query: string) {
  if (!query.trim()) return text;
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const regex = new RegExp(`(${escaped})`, 'gi');
  const parts = text.split(regex);
  return parts.map((part, index) =>
    regex.test(part) ? (
      <mark key={index} className="log-search-match">
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

export function LogViewer({ initialLogs = [], onStatsChange, className = '' }: LogViewerProps) {
  const [logs, setLogs] = useState<LogEntry[]>(initialLogs);
  const [levelFilter, setLevelFilter] = useState<string>('');
  const [categoryFilter, setCategoryFilter] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [autoScroll, setAutoScroll] = useState<boolean>(true);
  const [wrapLines, setWrapLines] = useState<boolean>(true);
  const [denseMode, setDenseMode] = useState<boolean>(false);
  const [showIsoTimestamp, setShowIsoTimestamp] = useState<boolean>(false);
  const [isPaused, setIsPaused] = useState<boolean>(false);
  const [pausedQueueCount, setPausedQueueCount] = useState<number>(0);
  const [copiedAll, setCopiedAll] = useState<boolean>(false);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [isUserScrolledUp, setIsUserScrolledUp] = useState<boolean>(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const scrollBodyRef = useRef<HTMLDivElement>(null);
  const pendingRef = useRef<LogEntry[]>([]);
  const pausedBufferRef = useRef<LogEntry[]>([]);
  const flushTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isPausedRef = useRef<boolean>(false);

  useEffect(() => {
    isPausedRef.current = isPaused;
  }, [isPaused]);

  const flushPendingLogs = useCallback(() => {
    flushTimerRef.current = null;
    if (isPausedRef.current) return;

    const batch = pendingRef.current;
    if (batch.length === 0) return;
    pendingRef.current = [];

    setLogs((prev) => {
      const merged = [...prev, ...batch];
      return merged.length > MAX_LOG_ENTRIES ? merged.slice(-MAX_LOG_ENTRIES) : merged;
    });
  }, []);

  const { isConnected } = useWebSocket({
    url: `${getWebSocketBaseUrl()}/ws/events`,
    topics: ['logs'],
    onMessage: (event) => {
      if (event.type === 'log') {
        const logEntry: LogEntry = {
          timestamp: new Date().toISOString(),
          level: normalizeLevel(event.level),
          message: normalizeMessage(event.message ?? event),
          source: typeof event.source === 'string' ? event.source : undefined,
          category: typeof event.category === 'string' ? event.category : undefined,
        };

        if (isPausedRef.current) {
          pausedBufferRef.current.push(logEntry);
          setPausedQueueCount(pausedBufferRef.current.length);
          return;
        }

        pendingRef.current.push(logEntry);
        if (!flushTimerRef.current) {
          flushTimerRef.current = setTimeout(flushPendingLogs, FLUSH_INTERVAL_MS);
        }
      }
    },
  });

  useEffect(() => {
    return () => {
      if (flushTimerRef.current) {
        clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
      pendingRef.current = [];
      pausedBufferRef.current = [];
    };
  }, []);

  const handleTogglePause = useCallback(() => {
    setIsPaused((prev) => {
      const next = !prev;
      if (!next && pausedBufferRef.current.length > 0) {
        const released = pausedBufferRef.current;
        pausedBufferRef.current = [];
        setPausedQueueCount(0);
        setLogs((current) => {
          const merged = [...current, ...released];
          return merged.length > MAX_LOG_ENTRIES ? merged.slice(-MAX_LOG_ENTRIES) : merged;
        });
      }
      return next;
    });
  }, []);

  const scrollToBottom = useCallback(() => {
    if (scrollBodyRef.current) {
      scrollBodyRef.current.scrollTop = scrollBodyRef.current.scrollHeight;
      setIsUserScrolledUp(false);
    }
  }, []);

  const handleScroll = useCallback(() => {
    if (!scrollBodyRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = scrollBodyRef.current;
    const distanceFromBottom = scrollHeight - scrollTop - clientHeight;
    setIsUserScrolledUp(distanceFromBottom > 48);
  }, []);

  useEffect(() => {
    if (autoScroll && !isUserScrolledUp && scrollBodyRef.current) {
      scrollBodyRef.current.scrollTop = scrollBodyRef.current.scrollHeight;
    }
  }, [logs.length, autoScroll, isUserScrolledUp]);

  const counts = useMemo(() => {
    let errors = 0;
    let warnings = 0;
    let info = 0;
    let debug = 0;
    for (const log of logs) {
      if (log.level === 'error') errors++;
      else if (log.level === 'warning') warnings++;
      else if (log.level === 'info') info++;
      else if (log.level === 'debug') debug++;
    }
    return { errors, warnings, info, debug };
  }, [logs]);

  const filteredLogs = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return logs.filter((log) => {
      if (levelFilter && log.level !== levelFilter) return false;
      if (categoryFilter && log.category?.toLowerCase() !== categoryFilter.toLowerCase()) {
        return false;
      }
      if (query) {
        const inMessage = log.message.toLowerCase().includes(query);
        const inSource = log.source?.toLowerCase().includes(query) ?? false;
        const inCategory = log.category?.toLowerCase().includes(query) ?? false;
        const inLevel = log.level.toLowerCase().includes(query);
        if (!inMessage && !inSource && !inCategory && !inLevel) return false;
      }
      return true;
    });
  }, [logs, levelFilter, categoryFilter, searchQuery]);

  const categories = useMemo(() => {
    const custom = new Set<string>();
    for (const log of logs) {
      if (log.category) custom.add(log.category.toLowerCase());
    }
    const merged = Array.from(new Set([...DEFAULT_CATEGORIES, ...Array.from(custom)]));
    return merged;
  }, [logs]);

  useEffect(() => {
    if (onStatsChange) {
      onStatsChange({
        total: logs.length,
        filtered: filteredLogs.length,
        errors: counts.errors,
        warnings: counts.warnings,
        info: counts.info,
        debug: counts.debug,
        isConnected,
        isPaused,
      });
    }
  }, [logs.length, filteredLogs.length, counts, isConnected, isPaused, onStatsChange]);

  const clearLogs = useCallback(() => {
    setLogs([]);
    pendingRef.current = [];
    pausedBufferRef.current = [];
    setPausedQueueCount(0);
    if (flushTimerRef.current) {
      clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
    }
  }, []);

  const handleExportLogs = useCallback(() => {
    const targetLogs = filteredLogs.length > 0 ? filteredLogs : logs;
    const lines = targetLogs.map(
      (log) =>
        `[${log.timestamp}] [${log.level.toUpperCase()}]${log.category ? ` [${log.category.toUpperCase()}]` : ''}${log.source ? ` [${log.source}]` : ''} ${log.message}`,
    );
    const content = lines.join('\n');
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ultimascraper-runtime-logs-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.log`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [filteredLogs, logs]);

  const handleCopyAll = useCallback(async () => {
    const targetLogs = filteredLogs.length > 0 ? filteredLogs : logs;
    const content = targetLogs
      .map(
        (log) =>
          `[${log.timestamp}] [${log.level.toUpperCase()}]${log.category ? ` [${log.category.toUpperCase()}]` : ''}${log.source ? ` [${log.source}]` : ''} ${log.message}`,
      )
      .join('\n');
    try {
      await navigator.clipboard.writeText(content);
      setCopiedAll(true);
      setTimeout(() => setCopiedAll(false), 2000);
    } catch {
      // fallback
    }
  }, [filteredLogs, logs]);

  const handleCopyLine = useCallback(async (index: number, log: LogEntry) => {
    const line = `[${log.timestamp}] [${log.level.toUpperCase()}]${log.category ? ` [${log.category.toUpperCase()}]` : ''}${log.source ? ` [${log.source}]` : ''} ${log.message}`;
    try {
      await navigator.clipboard.writeText(line);
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 1800);
    } catch {
      // fallback
    }
  }, []);

  const handleResetFilters = useCallback(() => {
    setLevelFilter('');
    setCategoryFilter('');
    setSearchQuery('');
  }, []);

  const activeFiltersCount =
    (levelFilter ? 1 : 0) + (categoryFilter ? 1 : 0) + (searchQuery.trim() ? 1 : 0);

  return (
    <div ref={containerRef} className={`atlas-log-viewer ${className}`.trim()}>
      {/* ── Control Console Strip ─────────────────────────────────── */}
      <div className="atlas-log-toolbar">
        <div className="atlas-log-toolbar__main">
          <div className="atlas-log-search">
            <svg
              className="atlas-log-search__icon"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <circle cx="11" cy="11" r="7" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <input
              type="text"
              className="atlas-log-search__input"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filter log text, category, or source (e.g. error, worker, jobs)..."
              aria-label="Filter logs"
            />
            {searchQuery && (
              <button
                type="button"
                className="atlas-log-search__clear"
                onClick={() => setSearchQuery('')}
                title="Clear search query"
                aria-label="Clear search"
              >
                ✕
              </button>
            )}
          </div>

          <div className="atlas-log-actions">
            <button
              type="button"
              className={`atlas-log-btn ${isPaused ? 'atlas-log-btn--warning' : ''}`}
              onClick={handleTogglePause}
              title={isPaused ? 'Resume stream' : 'Pause stream'}
            >
              {isPaused ? (
                <>
                  <svg className="atlas-log-btn__icon" viewBox="0 0 24 24" fill="currentColor">
                    <polygon points="5 3 19 12 5 21 5 3" />
                  </svg>
                  <span>Resume {pausedQueueCount > 0 ? `(${pausedQueueCount})` : ''}</span>
                </>
              ) : (
                <>
                  <svg className="atlas-log-btn__icon" viewBox="0 0 24 24" fill="currentColor">
                    <rect x="6" y="4" width="4" height="16" />
                    <rect x="14" y="4" width="4" height="16" />
                  </svg>
                  <span>Pause Stream</span>
                </>
              )}
            </button>

            <button
              type="button"
              className="atlas-log-btn"
              onClick={handleExportLogs}
              title="Download logs (.log)"
            >
              <svg
                className="atlas-log-btn__icon"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="7 10 12 15 17 10" />
                <line x1="12" y1="15" x2="12" y2="3" />
              </svg>
              <span>Export</span>
            </button>

            <button
              type="button"
              className="atlas-log-btn"
              onClick={handleCopyAll}
              title="Copy current visible logs to clipboard"
            >
              <svg
                className="atlas-log-btn__icon"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
              </svg>
              <span>{copiedAll ? 'Copied!' : 'Copy'}</span>
            </button>

            <button
              type="button"
              className="atlas-log-btn atlas-log-btn--danger"
              onClick={clearLogs}
              title="Clear current log buffer"
            >
              <svg
                className="atlas-log-btn__icon"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <polyline points="3 6 5 6 21 6" />
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              </svg>
              <span>Clear</span>
            </button>
          </div>
        </div>

        {/* ── Filters Row ─────────────────────────────────────────── */}
        <div className="atlas-log-toolbar__sub">
          {/* Level Filter Strip */}
          <div className="atlas-log-filter-group" role="group" aria-label="Severity level filter">
            <span className="atlas-log-filter-group__label">Severity:</span>
            <button
              type="button"
              className={`atlas-log-pill ${levelFilter === '' ? 'is-active' : ''}`}
              onClick={() => setLevelFilter('')}
            >
              All <span className="atlas-log-pill__count">{logs.length}</span>
            </button>
            <button
              type="button"
              className={`atlas-log-pill atlas-log-pill--error ${levelFilter === 'error' ? 'is-active' : ''}`}
              onClick={() => setLevelFilter(levelFilter === 'error' ? '' : 'error')}
            >
              Error <span className="atlas-log-pill__count">{counts.errors}</span>
            </button>
            <button
              type="button"
              className={`atlas-log-pill atlas-log-pill--warning ${levelFilter === 'warning' ? 'is-active' : ''}`}
              onClick={() => setLevelFilter(levelFilter === 'warning' ? '' : 'warning')}
            >
              Warn <span className="atlas-log-pill__count">{counts.warnings}</span>
            </button>
            <button
              type="button"
              className={`atlas-log-pill atlas-log-pill--info ${levelFilter === 'info' ? 'is-active' : ''}`}
              onClick={() => setLevelFilter(levelFilter === 'info' ? '' : 'info')}
            >
              Info <span className="atlas-log-pill__count">{counts.info}</span>
            </button>
            <button
              type="button"
              className={`atlas-log-pill atlas-log-pill--debug ${levelFilter === 'debug' ? 'is-active' : ''}`}
              onClick={() => setLevelFilter(levelFilter === 'debug' ? '' : 'debug')}
            >
              Debug <span className="atlas-log-pill__count">{counts.debug}</span>
            </button>
          </div>

          {/* Console View Preferences */}
          <div className="atlas-log-view-toggles">
            <label className="atlas-log-toggle" title="Toggle automatic scrolling to latest log">
              <input
                type="checkbox"
                checked={autoScroll}
                onChange={(e) => setAutoScroll(e.target.checked)}
              />
              <span className="atlas-log-toggle__indicator" />
              <span>Auto-scroll</span>
            </label>

            <label className="atlas-log-toggle" title="Wrap long log messages or display single line">
              <input
                type="checkbox"
                checked={wrapLines}
                onChange={(e) => setWrapLines(e.target.checked)}
              />
              <span className="atlas-log-toggle__indicator" />
              <span>Wrap lines</span>
            </label>

            <label className="atlas-log-toggle" title="Use compact line density">
              <input
                type="checkbox"
                checked={denseMode}
                onChange={(e) => setDenseMode(e.target.checked)}
              />
              <span className="atlas-log-toggle__indicator" />
              <span>Compact</span>
            </label>

            <label className="atlas-log-toggle" title="Toggle full ISO 8601 vs time-only timestamp">
              <input
                type="checkbox"
                checked={showIsoTimestamp}
                onChange={(e) => setShowIsoTimestamp(e.target.checked)}
              />
              <span className="atlas-log-toggle__indicator" />
              <span>ISO Time</span>
            </label>
          </div>
        </div>

        {/* Category Filter Strip */}
        <div className="atlas-log-categories" role="group" aria-label="Category filter">
          <span className="atlas-log-categories__label">Category:</span>
          <button
            type="button"
            className={`atlas-log-cat-btn ${categoryFilter === '' ? 'is-active' : ''}`}
            onClick={() => setCategoryFilter('')}
          >
            All Categories
          </button>
          {categories.map((cat) => (
            <button
              key={cat}
              type="button"
              className={`atlas-log-cat-btn atlas-log-cat-btn--${cat} ${categoryFilter === cat ? 'is-active' : ''}`}
              onClick={() => setCategoryFilter(categoryFilter === cat ? '' : cat)}
            >
              {cat.toUpperCase()}
            </button>
          ))}
          {activeFiltersCount > 0 && (
            <button
              type="button"
              className="atlas-log-reset-filters"
              onClick={handleResetFilters}
              title="Reset all active search and filter constraints"
            >
              Reset Filters ({activeFiltersCount})
            </button>
          )}
        </div>
      </div>

      {/* ── Terminal Feed Header Bar ──────────────────────────────── */}
      <div className="atlas-log-terminal-header">
        <div className="atlas-log-terminal-header__left">
          <span
            className={`atlas-log-dot ${isConnected ? (isPaused ? 'is-paused' : 'is-connected') : 'is-disconnected'}`}
          />
          <span className="atlas-log-terminal-header__title">
            TERMINAL FEED // {isPaused ? 'PAUSED' : isConnected ? 'STREAMING' : 'OFFLINE'}
          </span>
          <span className="atlas-log-terminal-header__ws">
            {isConnected ? '/ws/events: 200 OK' : '/ws/events: DISCONNECTED'}
          </span>
        </div>

        <div className="atlas-log-terminal-header__right">
          <span className="atlas-log-terminal-header__capacity">
            BUFFER: {filteredLogs.length} / {logs.length} RECORDED (MAX {MAX_LOG_ENTRIES})
          </span>
          {isUserScrolledUp && (
            <button
              type="button"
              className="atlas-log-jump-btn"
              onClick={scrollToBottom}
              title="Jump to latest incoming logs"
            >
              ↓ Jump to latest
            </button>
          )}
        </div>
      </div>

      {/* ── Terminal Log Entries ──────────────────────────────────── */}
      <div
        ref={scrollBodyRef}
        onScroll={handleScroll}
        className={`atlas-log-body ${wrapLines ? 'is-wrapped' : 'is-nowrap'} ${denseMode ? 'is-dense' : ''}`}
        tabIndex={0}
        role="log"
        aria-live="polite"
      >
        {filteredLogs.length === 0 ? (
          <div className="atlas-log-empty">
            {logs.length === 0 ? (
              <div className="atlas-log-empty__card">
                <div className="atlas-log-empty__radar" aria-hidden="true">
                  <div className="atlas-log-empty__beam" />
                </div>
                <strong className="atlas-log-empty__title">Awaiting Telemetry Stream</strong>
                <p className="atlas-log-empty__text">
                  Connected to backend event pipeline at <code>/ws/events</code>. System events,
                  scraper workers, and background jobs will emit operational records here.
                </p>
                <div className="atlas-log-empty__meta">
                  <span>WS STATUS: {isConnected ? 'CONNECTED' : 'STANDBY'}</span>
                  <span>BUFFER: 0 / {MAX_LOG_ENTRIES}</span>
                </div>
              </div>
            ) : (
              <div className="atlas-log-empty__card">
                <strong className="atlas-log-empty__title">No Matching Log Records</strong>
                <p className="atlas-log-empty__text">
                  No log entries matched your current criteria
                  {levelFilter ? ` (severity: ${levelFilter})` : ''}
                  {categoryFilter ? ` (category: ${categoryFilter})` : ''}
                  {searchQuery ? ` (search: "${searchQuery}")` : ''}.
                </p>
                <button
                  type="button"
                  className="atlas-log-btn atlas-log-btn--primary"
                  onClick={handleResetFilters}
                >
                  Reset Active Filters
                </button>
              </div>
            )}
          </div>
        ) : (
          filteredLogs.map((log, index) => {
            const isCopyFeedback = copiedIndex === index;
            return (
              <div
                key={`${log.timestamp}-${index}`}
                className={`atlas-log-row atlas-log-row--${log.level}`}
              >
                <span className="atlas-log-row__idx">
                  {String(index + 1).padStart(4, '0')}
                </span>
                <span className="atlas-log-row__time" title={log.timestamp}>
                  {formatTime(log.timestamp, showIsoTimestamp)}
                </span>
                <span className={`atlas-log-badge atlas-log-badge--${log.level}`}>
                  {log.level.toUpperCase()}
                </span>
                {log.category && (
                  <span className={`atlas-log-tag atlas-log-tag--${log.category.toLowerCase()}`}>
                    [{log.category.toUpperCase()}]
                  </span>
                )}
                {log.source && (
                  <span className="atlas-log-source" title={`Source: ${log.source}`}>
                    [{log.source}]
                  </span>
                )}
                <span className="atlas-log-row__message">
                  {highlightText(log.message, searchQuery)}
                </span>
                <button
                  type="button"
                  className="atlas-log-row__copy-btn"
                  onClick={() => handleCopyLine(index, log)}
                  title={isCopyFeedback ? 'Copied line!' : 'Copy line'}
                  aria-label="Copy log line"
                >
                  {isCopyFeedback ? '✓' : '⧉'}
                </button>
              </div>
            );
          })
        )}
      </div>

      {/* ── Scrolled Up Floating Indicator ────────────────────────── */}
      {isUserScrolledUp && (
        <div className="atlas-log-floating-banner">
          <span>Scrolled up // new telemetry streaming in background</span>
          <button type="button" className="atlas-log-jump-pill" onClick={scrollToBottom}>
            ↓ Scroll to bottom
          </button>
        </div>
      )}
    </div>
  );
}
