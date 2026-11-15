import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  commandSplitScan,
  getConsolidationStatus,
  getSplitScan,
  previewConsolidation,
  startConsolidation,
  startSplitScan,
  type ConsolidationPreview,
  type ConsolidationRunEntry,
  type ConsolidationStatus,
  type ScanCommand,
  type SplitScan,
} from '../../../api/consolidation';
import { copyText } from '../../../utils/clipboard';
import { formatBytes, requestErrorMessage } from '../../system/lib/systemUtils';
import {
  bytesFor,
  driveSpaces,
  driveUsage,
  performerFit,
  tickWhereTheyFit,
  type PerformerFit,
} from '../lib/splitSpace';
import './SplitPerformersTool.css';

const POLL_MS = 3000;

function formatTime(seconds?: number | null): string {
  return seconds ? new Date(seconds * 1000).toLocaleString() : 'never';
}

function percent(done: number, total: number): number {
  return total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
}

/** A warning (reserve) or error (no space) for a performer with a target, if any. */
function spaceNote(fit: PerformerFit | null, isSelected: boolean): { tone: 'warning' | 'error'; text: string } | null {
  if (!fit?.space || fit.fit === 'ok') return null;
  const { root, needed, committed, space } = fit;
  const others = committed > 0 ? ' with the other ticked performers' : '';
  if (fit.fit === 'no_space' && !isSelected) {
    return {
      tone: 'error',
      text: `Not enough space on ${root}${others}: needs ${formatBytes(needed)}, ${formatBytes(
        Math.max(space.free - committed, 0),
      )} left.`,
    };
  }
  const dip = Math.min(committed + needed - (space.free - space.reserve), space.reserve);
  return {
    tone: 'warning',
    text: `Uses ${formatBytes(dip)} of the ${formatBytes(space.reserve)} reserve on ${root}${others}.`,
  };
}

/** Why a performer has no target; red when it is short of space. */
function refusalNote(
  preview: ConsolidationPreview,
  chosen: string | undefined,
): { tone: 'warning' | 'error'; text: string } {
  if (!preview.no_space) return { tone: 'warning', text: preview.reason };
  const folder = preview.folders.find((candidate) => candidate.root === chosen);
  const needed = chosen ? bytesFor(preview, chosen) : null;
  if (folder?.free_bytes != null && needed != null) {
    return {
      tone: 'error',
      text: `Not enough space on ${folder.root}: needs ${formatBytes(needed)}, ${formatBytes(
        Math.max(folder.free_bytes, 0),
      )} free.`,
    };
  }
  return { tone: 'error', text: 'Not enough free space on any drive holding this performer.' };
}

function runOutcome(entry: ConsolidationRunEntry): string {
  if (entry.error) return entry.error;
  return `${entry.moved ?? 0} files moved (${formatBytes(entry.moved_bytes ?? 0)}), ${entry.duplicates ?? 0} duplicates removed, ${
    entry.conflict_count ?? 0
  } name clashes left, ${entry.failed_count ?? 0} failed`;
}

/** A path that copies itself to the clipboard when clicked; `label` is what shows, if not the path. */
function CopyPath({ path, label, className = '' }: { path: string; label?: string; className?: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  const copy = async () => {
    try {
      await copyText(path);
      setState('copied');
    } catch {
      setState('failed');
    }
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setState('idle'), 1500);
  };

  return (
    <button
      type="button"
      className={`split-copy ${className}${state !== 'idle' ? ` is-${state}` : ''}`}
      title={state === 'copied' ? 'Copied' : state === 'failed' ? 'Copy failed' : `Copy ${path}`}
      aria-label={`Copy ${path}`}
      onClick={() => void copy()}
    >
      {/* Feedback is the icon and colour only, so the path never changes width. */}
      <code>{label ?? path}</code>
      <span className="split-copy__icon" aria-hidden="true">
        {state === 'copied' ? '✓' : state === 'failed' ? '✕' : '⧉'}
      </span>
      <span className="split-copy__status" role="status">
        {state === 'copied' ? 'Copied' : state === 'failed' ? 'Copy failed' : ''}
      </span>
    </button>
  );
}

export function SplitPerformersTool() {
  const [scan, setScan] = useState<SplitScan | null>(null);
  const [status, setStatus] = useState<ConsolidationStatus>({});
  const [previews, setPreviews] = useState<Record<string, ConsolidationPreview>>({});
  const [previewing, setPreviewing] = useState<string | null>(null);
  const [previewErrors, setPreviewErrors] = useState<Record<string, string>>({});
  // Drives the user picked; performers without one get the best drive.
  const [targets, setTargets] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<string[]>([]);
  // Previews that asked to be ticked; ticked once they fit beside the others.
  const [pendingTicks, setPendingTicks] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [nextScan, nextStatus] = await Promise.all([getSplitScan(), getConsolidationStatus()]);
      setScan(nextScan);
      setStatus(nextStatus);
    } catch (refreshError) {
      setError(requestErrorMessage(refreshError, 'Failed to load consolidation state'));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const busy = Boolean(scan?.scanning || status.running);
  useEffect(() => {
    if (!busy) return undefined;
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [busy, refresh]);

  const scanNow = async () => {
    setError(null);
    try {
      await startSplitScan();
      setPreviews({});
      setPreviewErrors({});
      setTargets({});
      setSelected([]);
      setPendingTicks([]);
      await refresh();
    } catch (scanError) {
      setError(requestErrorMessage(scanError, 'Failed to start the scan'));
    }
  };

  const commandScan = async (command: ScanCommand) => {
    setError(null);
    try {
      await commandSplitScan(command);
      await refresh();
    } catch (commandError) {
      setError(requestErrorMessage(commandError, `Failed to ${command} the scan`));
    }
  };

  const preview = useCallback(async (relativePath: string, targetRoot?: string) => {
    setPreviewing(relativePath);
    setPreviewErrors((current) => {
      const next = { ...current };
      delete next[relativePath];
      return next;
    });
    try {
      const result = await previewConsolidation(relativePath, targetRoot);
      setPreviews((current) => ({ ...current, [relativePath]: result }));
      // Ticked when the user chose a drive that turned out valid, or when nothing
      // needs moving and consolidating only tidies up the other copies.
      const chosenAndValid = Boolean(targetRoot) && result.target_root === targetRoot;
      const nothingToMove = Boolean(result.target_root) && result.move_files === 0;
      if (chosenAndValid || nothingToMove) {
        setPendingTicks((current) => (current.includes(relativePath) ? current : [...current, relativePath]));
      }
    } catch (previewError) {
      setPreviewErrors((current) => ({
        ...current,
        [relativePath]: requestErrorMessage(previewError, 'Preview failed'),
      }));
    } finally {
      setPreviewing(null);
    }
  }, []);

  // A finished run moved files, so every earlier preview is out of date.
  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && !status.running) {
      setPreviews({});
      setPreviewErrors({});
      setTargets({});
      setSelected([]);
      setPendingTicks([]);
    }
    wasRunning.current = Boolean(status.running);
  }, [status.running]);

  const performers = scan?.performers ?? [];
  const spaces = useMemo(() => driveSpaces(Object.values(previews)), [previews]);
  const fitOf = (path: string, within: readonly string[] = selected) => performerFit(path, previews, within, spaces);

  // Auto-ticks never overfill a drive: each is counted against those ticked before it.
  useEffect(() => {
    if (pendingTicks.length === 0) return;
    setSelected((current) => tickWhereTheyFit(pendingTicks, previews, current, spaces));
    setPendingTicks([]);
  }, [pendingTicks, previews, spaces]);

  // Preview one performer at a time: each one walks its folders on the network drives.
  const nextToPreview = performers.find(
    (performer) => !previews[performer.relative_path] && !previewErrors[performer.relative_path],
  )?.relative_path;
  useEffect(() => {
    if (busy || previewing !== null || !nextToPreview) return;
    void preview(nextToPreview, targets[nextToPreview]);
  }, [busy, previewing, nextToPreview, preview, targets]);

  // Re-previewed against the chosen drive before it can be selected again.
  const chooseTarget = (relativePath: string, root: string | null) => {
    const without = <T,>(record: Record<string, T>): Record<string, T> => {
      const next = { ...record };
      delete next[relativePath];
      return next;
    };
    setTargets((current) => (root ? { ...current, [relativePath]: root } : without(current)));
    setPreviews(without);
    setPreviewErrors(without);
    setSelected((current) => current.filter((value) => value !== relativePath));
    setPendingTicks((current) => current.filter((value) => value !== relativePath));
  };

  const toggle = (relativePath: string) =>
    setSelected((current) => {
      if (current.includes(relativePath)) return current.filter((value) => value !== relativePath);
      // A performer that no longer fits beside the ticked ones stays unticked.
      return performerFit(relativePath, previews, current, spaces)?.fit === 'no_space'
        ? current
        : [...current, relativePath];
    });

  const run = async () => {
    setError(null);
    try {
      await startConsolidation(
        selected,
        Object.fromEntries(selected.filter((path) => targets[path]).map((path) => [path, targets[path]])),
      );
      setSelected([]);
      await refresh();
    } catch (runError) {
      setError(requestErrorMessage(runError, 'Failed to start consolidation'));
    }
  };

  const previewedCount = performers.filter((performer) => previews[performer.relative_path]).length;
  const selectedBytes = selected.reduce((sum, path) => sum + (previews[path]?.move_bytes ?? 0), 0);
  const usage = driveUsage(previews, selected, spaces);
  const scanCancelled =
    !scan?.scanning && !scan?.interrupted && scan?.cancelled_at && (scan.scanned_at ?? 0) < scan.cancelled_at;
  const lastRun = !status.running ? status.performers ?? [] : [];

  return (
    <div className="tools-panel split-tool">
      <div className="tools-panel-head">
        <span className="tools-step">FS</span>
        <div>
          <h2>Split Performers</h2>
          <p>
            Performers whose folder is on more than one drive. Each is previewed in turn to show which drive their files
            would move to: the highest-priority drive that already holds them and keeps its reserve. A move may use a
            drive's reserve, with a warning, but never more than its free space.
          </p>
        </div>
      </div>

      <div className="split-layout">
        <div className="split-main">
          {scan?.scanning && (
            <div className="split-progress" role="status">
              <div className="split-progress__label">
                <span>
                  {scan.paused ? 'Paused on' : 'Scanning'} drive{' '}
                  {Math.min((scan.roots_done ?? 0) + 1, scan.roots_total ?? 1)} of {scan.roots_total ?? '?'}
                </span>
                {scan.current_root && <code>{scan.current_root}</code>}
              </div>
              <div className="split-progress__track">
                <span style={{ width: `${percent(scan.roots_done ?? 0, scan.roots_total ?? 0)}%` }} />
              </div>
              {scan.paused && <p className="split-muted">Resume carries on from this drive.</p>}
            </div>
          )}
          {status.running && (
            <div className="split-progress" role="status">
              <div className="split-progress__label">
                <span>
                  Consolidating {(status.done ?? 0) + 1} of {status.total}
                </span>
                {status.current && <code>{status.current}</code>}
              </div>
              <div className="split-progress__track">
                <span style={{ width: `${percent(status.done ?? 0, status.total ?? 0)}%` }} />
              </div>
            </div>
          )}
          {scan?.error && (
            <div className="tools-alert error" role="alert">
              {scan.error}
            </div>
          )}
          {!scan?.scanning && scan?.interrupted && (
            <div className="tools-alert warning" role="alert">
              The last scan stopped when the backend restarted; scan again to finish it.
            </div>
          )}
          {scanCancelled && (
            <div className="tools-alert warning">
              Scan cancelled {formatTime(scan?.cancelled_at)}; the list is from the last finished scan.
            </div>
          )}
          {error && (
            <div className="tools-alert error" role="alert">
              {error}
            </div>
          )}

          {performers.length === 0 ? (
            <div className="split-empty">
              <strong>{scan?.scanned_at ? 'No performer is split across drives.' : 'No scan yet'}</strong>
              <span>
                {scan?.scanned_at
                  ? `Last scanned ${formatTime(scan.scanned_at)}.`
                  : 'Scan the drives to find performers whose folder is on more than one of them.'}
              </span>
            </div>
          ) : (
            <ul className="split-list" aria-label="Split performers">
              {performers.map((performer) => {
                const result = previews[performer.relative_path];
                const isSelected = selected.includes(performer.relative_path);
                const fit = fitOf(performer.relative_path);
                const blocked = !isSelected && fit?.fit === 'no_space';
                const note = result?.target_root
                  ? spaceNote(fit, isSelected)
                  : result
                    ? refusalNote(result, targets[performer.relative_path])
                    : null;
                const tone = note?.tone ?? (result?.target_root ? 'ready' : null);
                return (
                  <li
                    key={performer.relative_path}
                    className={`split-row${isSelected ? ' is-selected' : ''}${tone ? ` is-${tone}` : ''}`}
                  >
                    <label
                      className="split-row__select"
                      title={!result?.target_root ? 'No target drive' : blocked ? 'Not enough space' : undefined}
                    >
                      <input
                        type="checkbox"
                        aria-label={`Select ${performer.relative_path}`}
                        checked={isSelected}
                        onChange={() => toggle(performer.relative_path)}
                        disabled={!result?.target_root || busy || blocked}
                      />
                    </label>
                    <div className="split-row__body">
                      <div className="split-row__title">
                        <CopyPath path={performer.relative_path} className="split-copy--title" />
                        <span className="split-muted">{(result?.folders ?? performer.folders).length} drives</span>
                      </div>
                      <ul className="split-drives">
                        {(result?.folders ?? performer.folders).map((folder) => {
                          const chosen = targets[performer.relative_path] === folder.root;
                          const isTarget = result?.target_root === folder.root;
                          return (
                            <li
                              key={folder.root}
                              className={`split-drive${isTarget ? ' is-target' : ''}${chosen ? ' is-chosen' : ''}${
                                chosen && result?.no_space ? ' is-short' : ''
                              }`}
                            >
                              <CopyPath path={folder.path} label={folder.root} />
                              <button
                                type="button"
                                className="split-drive__choose"
                                aria-pressed={chosen}
                                aria-label={`Move ${performer.relative_path} to ${folder.root}`}
                                title={chosen ? 'Chosen target' : 'Make this the target'}
                                onClick={() => !chosen && chooseTarget(performer.relative_path, folder.root)}
                                disabled={busy || previewing === performer.relative_path}
                              >
                                <span className="split-drive__meta">
                                  P{folder.priority}
                                  {folder.bytes != null && ` · ${folder.files} files · ${formatBytes(folder.bytes)}`}
                                </span>
                                {isTarget && <span className="split-drive__tag">{chosen ? 'chosen' : 'target'}</span>}
                              </button>
                            </li>
                          );
                        })}
                      </ul>
                      {targets[performer.relative_path] && (
                        <button
                          type="button"
                          className="split-row__reset"
                          onClick={() => chooseTarget(performer.relative_path, null)}
                          disabled={busy || previewing === performer.relative_path}
                        >
                          Use best drive
                        </button>
                      )}
                      {!result && (
                        <p
                          className={`split-row__plan ${previewErrors[performer.relative_path] ? 'is-failed' : 'is-pending'}`}
                          role={previewErrors[performer.relative_path] ? 'alert' : undefined}
                        >
                          {previewErrors[performer.relative_path]
                            ? `Preview failed: ${previewErrors[performer.relative_path]}`
                            : previewing === performer.relative_path
                              ? 'Previewing…'
                              : busy
                                ? 'Previews when the scan or run finishes.'
                                : 'Waiting to preview.'}
                        </p>
                      )}
                      {result?.target_root && (
                        <p className="split-row__plan">
                          Moves <strong>{result.move_files}</strong> files ({formatBytes(result.move_bytes)}), removes{' '}
                          <strong>{result.duplicates}</strong> duplicates. Leaves {result.conflicts.length} same-named
                          files of a different size, {result.recent} changed in the last 10 minutes and{' '}
                          {result.too_long} with paths too long.
                        </p>
                      )}
                      {note && (
                        <p className={`split-row__plan is-${note.tone}`} role="alert">
                          {note.text}
                        </p>
                      )}
                    </div>
                    {previewErrors[performer.relative_path] && (
                      <button
                        type="button"
                        className="tools-btn tools-btn-secondary split-row__action"
                        onClick={() => void preview(performer.relative_path, targets[performer.relative_path])}
                        disabled={previewing !== null || busy}
                      >
                        Retry
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          {lastRun.length > 0 && (
            <details className="split-results">
              <summary>
                Last run · {lastRun.length} performer{lastRun.length === 1 ? '' : 's'} · finished{' '}
                {formatTime(status.finished_at)}
              </summary>
              <ul>
                {lastRun.map((entry) => (
                  <li key={entry.relative_path} className={entry.error ? 'is-failed' : undefined}>
                    <CopyPath path={entry.relative_path} />
                    <span>{runOutcome(entry)}</span>
                    {(entry.conflicts ?? []).length > 0 && (
                      <ul className="split-results__conflicts">
                        {(entry.conflicts ?? []).map((path) => (
                          <li key={path}>
                            <CopyPath path={path} />
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>

        <aside className="split-run" aria-label="Consolidation">
          <header>Run</header>
          <dl className="split-run__stats">
            <div>
              <dt>Split performers</dt>
              <dd>{performers.length.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Previewed</dt>
              <dd>
                {previewedCount.toLocaleString()} / {performers.length.toLocaleString()}
              </dd>
            </div>
            <div>
              <dt>Selected</dt>
              <dd className={selected.length ? 'is-accent' : undefined}>{selected.length.toLocaleString()}</dd>
            </div>
            <div>
              <dt>To move</dt>
              <dd>{formatBytes(selectedBytes)}</dd>
            </div>
            <div>
              <dt>Last scan</dt>
              <dd className="split-run__time">{formatTime(scan?.scanned_at)}</dd>
            </div>
          </dl>
          {usage.length > 0 && (
            <ul className="split-run__drives" aria-label="Space on target drives">
              {usage.map((drive) => {
                const tone =
                  drive.used > drive.free ? 'error' : drive.used > drive.free - drive.reserve ? 'warning' : 'ok';
                const reserveAt = drive.free > 0 ? Math.max(0, (drive.free - drive.reserve) / drive.free) * 100 : 0;
                return (
                  <li key={drive.root} className={`split-run__drive is-${tone}`}>
                    <div className="split-run__drive-label">
                      <CopyPath path={drive.root} />
                      <span>
                        {formatBytes(drive.used)} of {formatBytes(Math.max(drive.free, 0))} free
                      </span>
                    </div>
                    <div className="split-run__drive-track" title={`Reserve: ${formatBytes(drive.reserve)}`}>
                      <span style={{ width: `${Math.min(100, drive.free > 0 ? (drive.used / drive.free) * 100 : 100)}%` }} />
                      {drive.reserve > 0 && <i style={{ left: `${reserveAt}%` }} aria-hidden="true" />}
                    </div>
                    {tone === 'warning' && <p>Uses some of its {formatBytes(drive.reserve)} reserve.</p>}
                  </li>
                );
              })}
            </ul>
          )}
          <div className="split-run__actions">
            {scan?.scanning ? (
              <div className="split-run__pair">
                <button
                  type="button"
                  className="tools-btn tools-btn-secondary"
                  onClick={() => void commandScan(scan.paused ? 'resume' : 'pause')}
                >
                  {scan.paused ? 'Resume scan' : 'Pause scan'}
                </button>
                <button type="button" className="tools-btn tools-btn-secondary" onClick={() => void commandScan('cancel')}>
                  Cancel scan
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="tools-btn tools-btn-secondary"
                onClick={() => void scanNow()}
                disabled={busy}
              >
                Scan for split performers
              </button>
            )}
            <button
              type="button"
              className="tools-btn tools-btn-primary"
              onClick={() => void run()}
              disabled={selected.length === 0 || busy}
            >
              Consolidate {selected.length} selected
            </button>
            <p className="split-muted" role="status">
              {previewing
                ? `Previewing ${previewedCount + 1} of ${performers.length}…`
                : 'Click a drive to make it the target. Only performers with a target can be selected.'}
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}
