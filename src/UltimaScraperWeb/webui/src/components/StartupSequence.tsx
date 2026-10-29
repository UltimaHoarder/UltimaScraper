import { useCallback, useEffect, useRef, useState } from 'react';
import './StartupSequence.css';
import { StartupBrand } from './StartupBrand';
import {
  applyStartupMigration,
  discardStartupMigration,
  previewStartupMigration,
  regenerateStartupMigration,
} from '../api/setup';
import type { StartupMigrationPreviewResponse } from '../api/types/setup';
import { connectionScopedKey } from '../api/http';
import {
  hasMigrationCheckForStartup,
  recordMigrationCheckForStartup,
} from '../app/bootstrap/startupMigrationState';
import { writeStorage } from '../shared/lib/browserStorage';

const LAST_RESULT_KEY = 'usr_last_startup_result';
const READY_HANDOFF_DELAY_MS = 450;
const SLOW_CONNECTION_DELAY_MS = 10_000;

type StartupPhase = 'connecting' | 'previewing' | 'review' | 'applying' | 'ready' | 'error';
type StartupOutcome = 'checked' | 'applied' | 'skipped';

let inFlightPreview: {
  startupId: string;
  request: Promise<StartupMigrationPreviewResponse>;
} | null = null;

const previewStartupMigrationOnce = (
  backendStartupId: string,
): Promise<StartupMigrationPreviewResponse> => {
  if (inFlightPreview?.startupId === backendStartupId) {
    return inFlightPreview.request;
  }

  const request = previewStartupMigration();
  inFlightPreview = { startupId: backendStartupId, request };
  const clearRequest = () => {
    if (inFlightPreview?.request === request) {
      inFlightPreview = null;
    }
  };
  void request.then(clearRequest, clearRequest);
  return request;
};

const describeError = (value: unknown): string => {
  if (value instanceof Error) return value.message;
  if (typeof value === 'string') return value;
  return 'The operation did not complete. Check the backend logs for details.';
};

export function StartupSequence({
  error,
  backendStartupId,
  canRunMigrationCheck = true,
  connectionAttempt = 1,
  isRetrying = false,
  onRetry,
  onReady,
}: {
  error: unknown;
  backendStartupId: string | null;
  canRunMigrationCheck?: boolean;
  connectionAttempt?: number;
  isRetrying?: boolean;
  onRetry?: () => void;
  onReady?: () => void;
}) {
  const [messages, setMessages] = useState<string[]>(['Initializing...']);
  const [phase, setPhase] = useState<StartupPhase>('connecting');
  const [preview, setPreview] = useState<StartupMigrationPreviewResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [connectionSlow, setConnectionSlow] = useState(false);
  const [operationError, setOperationError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const primaryReviewActionRef = useRef<HTMLButtonElement>(null);
  const migrationStarted = useRef(false);
  const readyNotified = useRef(false);

  const appendMessages = useCallback((next: string[]) => {
    if (!next.length) return;
    setMessages(prev => [...prev, ...next.filter(Boolean)]);
  }, []);

  const markReady = useCallback((message: string, outcome: StartupOutcome, resultPreview?: StartupMigrationPreviewResponse | null) => {
    if (!backendStartupId) {
      throw new Error('Backend bootstrap did not provide a startup identifier.');
    }
    if (message) appendMessages([message]);
    setPhase('ready');
    recordMigrationCheckForStartup(backendStartupId);
    writeStorage(connectionScopedKey(LAST_RESULT_KEY), JSON.stringify({
      startup_id: backendStartupId,
      completed_at: new Date().toISOString(),
      outcome,
      message,
      revision: resultPreview?.revision ?? null,
      filename: resultPreview?.filename ?? null,
    }));
    if (!readyNotified.current) {
      readyNotified.current = true;
      setTimeout(() => onReady?.(), READY_HANDOFF_DELAY_MS);
    }
  }, [appendMessages, backendStartupId, onReady]);

  useEffect(() => {
    if (canRunMigrationCheck || error) {
      return;
    }
    const timer = window.setTimeout(() => setConnectionSlow(true), SLOW_CONNECTION_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [canRunMigrationCheck, error]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  useEffect(() => {
    if (phase === 'review') {
      primaryReviewActionRef.current?.focus();
    }
  }, [phase]);

  const startMigrationReview = useCallback(async () => {
    if (!backendStartupId) {
      throw new Error('Backend bootstrap did not provide a startup identifier.');
    }
    setPhase('previewing');
    setOperationError(null);
    appendMessages(['Backend connected', 'Generating migration preview...']);
    setBusy(true);

    try {
      const result = await previewStartupMigrationOnce(backendStartupId);
      appendMessages(result.output ?? []);
      appendMessages([result.message]);

      if (result.status === 'completed') {
        markReady(result.message, result.outcome ?? 'checked', result);
        return;
      }
      if (result.status === 'requires_database') {
        markReady('Database not configured yet. Migration check skipped.', 'skipped', result);
        return;
      }
      if (result.status === 'no_changes') {
        markReady('✓ Database schema is up to date', 'checked', result);
        return;
      }
      if (result.status === 'ready') {
        setPreview(result);
        setPhase('review');
        appendMessages([result.has_changes ? 'Pending migration operations require approval before startup can continue.' : 'Revision bookkeeping requires approval before startup can continue.']);
        return;
      }
      setOperationError(result.message || 'Migration preview failed.');
      setPhase('error');
    } catch (err) {
      const detail = describeError(err);
      appendMessages([`Migration preview failed: ${detail}`]);
      setOperationError(detail);
      setPhase('error');
    } finally {
      setBusy(false);
    }
  }, [appendMessages, backendStartupId, markReady]);

  useEffect(() => {
    if (error) {
      setMessages(prev => {
        const last = prev[prev.length - 1];
        if (last !== 'Waiting for backend...') {
          return [...prev, 'Waiting for backend...'];
        }
        return prev;
      });
      return;
    }

    if (!canRunMigrationCheck) {
      return;
    }

    if (!backendStartupId) {
      setOperationError('Backend bootstrap did not provide a startup identifier.');
      setPhase('error');
      return;
    }

    if (hasMigrationCheckForStartup(backendStartupId)) {
      appendMessages(['Backend connected', '✓ Already up to date']);
      markReady('✓ Startup checks complete', 'checked');
      return;
    }

    if (!migrationStarted.current) {
      migrationStarted.current = true;
      void startMigrationReview();
    }
  }, [appendMessages, backendStartupId, canRunMigrationCheck, error, markReady, startMigrationReview]);

  const applyMigration = async () => {
    if (!preview?.preview_id) return;
    setBusy(true);
    setPhase('applying');
    setOperationError(null);
    appendMessages(['Applying reviewed migration. Database operations may take several minutes; index builds can also wait for existing transactions to finish...']);
    try {
      const result = await applyStartupMigration({ preview_id: preview.preview_id });
      appendMessages(result.output ?? []);
      appendMessages([result.message]);
      if (result.success) {
        setPreview(null);
        markReady('✓ Database migration complete', 'applied', preview);
        return;
      }
      setOperationError(result.message);
      setPhase('review');
    } catch (err) {
      const detail = describeError(err);
      const message = `${detail}. The request ended without confirming the database result; the migration may still be running. Refresh the preview to check its state before retrying.`;
      appendMessages([message]);
      setOperationError(message);
      setPhase('review');
    } finally {
      setBusy(false);
    }
  };

  const discardMigration = async () => {
    setBusy(true);
    setOperationError(null);
    appendMessages(['Skipping migration for this startup...']);
    try {
      const result = await discardStartupMigration();
      appendMessages(result.output ?? []);
      appendMessages([result.message]);
      setPreview(null);
      markReady('Migration skipped for this startup.', 'skipped', preview);
    } catch (err) {
      const detail = describeError(err);
      appendMessages([`Unable to skip migration: ${detail}`]);
      setOperationError(detail);
      setPhase('error');
    } finally {
      setBusy(false);
    }
  };

  const regenerateMigration = async () => {
    setBusy(true);
    setPhase('previewing');
    setOperationError(null);
    appendMessages(['Regenerating migration preview...']);
    try {
      const result = await regenerateStartupMigration();
      appendMessages(result.output ?? []);
      appendMessages([result.message]);
      if (result.status === 'ready') {
        setPreview(result);
        setPhase('review');
        return;
      }
      if (result.status === 'no_changes' || result.status === 'requires_database') {
        setPreview(null);
        markReady(result.status === 'no_changes'
          ? '✓ Database schema is up to date'
          : 'Database not configured yet. Migration check skipped.',
        result.status === 'no_changes' ? 'checked' : 'skipped', result);
        return;
      }
      setOperationError(result.message || 'Migration preview regeneration failed.');
      setPhase('error');
    } catch (err) {
      const detail = describeError(err);
      appendMessages([`Regenerate failed: ${detail}`]);
      setOperationError(detail);
      setPhase('error');
    } finally {
      setBusy(false);
    }
  };

  const statusText = error && !canRunMigrationCheck ? 'Backend unavailable' : ({
    connecting: 'Connecting to backend...',
    previewing: 'Checking database schema...',
    review: 'Migration approval required',
    applying: 'Applying database migration...',
    ready: 'Startup complete',
    error: 'Startup check failed',
  }[phase]);

  const hasStartupError = phase === 'error' || Boolean(error && !canRunMigrationCheck);
  const connectionDetail = !canRunMigrationCheck
    ? error
      ? describeError(error)
      : connectionSlow
        ? 'The backend is taking longer than expected to respond.'
        : null
    : null;

  return (
    <div className="startup-container" data-state={hasStartupError ? 'error' : connectionSlow && !canRunMigrationCheck ? 'slow' : phase}>
      <div className="startup-inner">
        <div className="startup-glow" />

        <StartupBrand />

        <div className="startup-status-bar" role="status" aria-live="polite" aria-atomic="true">
          {phase !== 'ready' && !hasStartupError && (
            <div className="startup-pulse" />
          )}
          {phase === 'ready' && <span className="startup-check">✓</span>}
          {hasStartupError && <span className="startup-x">✗</span>}
          <span className="startup-status-text">{statusText}</span>
        </div>

        {phase === 'connecting' && (
          <div className="startup-connection-meta">
            <span>Connection attempt {Math.max(1, connectionAttempt)}</span>
            {isRetrying && <span>Retry in progress</span>}
          </div>
        )}

        {connectionDetail && (
          <div className={`startup-notice ${error ? 'startup-notice-error' : 'startup-notice-warning'}`} role="alert">
            <strong>{error ? 'Could not reach the backend.' : 'Still connecting.'}</strong>
            <span>{connectionDetail}</span>
            {onRetry && (
              <button type="button" className="startup-btn startup-btn-secondary" disabled={isRetrying} onClick={onRetry}>
                {isRetrying ? 'Retrying…' : 'Retry connection'}
              </button>
            )}
          </div>
        )}

        {phase === 'error' && operationError && (
          <div className="startup-notice startup-notice-error" role="alert">
            <strong>Database startup check failed.</strong>
            <span>{operationError}</span>
            <button
              type="button"
              className="startup-btn startup-btn-secondary"
              disabled={busy}
              onClick={() => { void startMigrationReview(); }}
            >
              Retry database check
            </button>
          </div>
        )}

        <div className="startup-terminal" ref={scrollRef} role="log" aria-live="polite" aria-relevant="additions">
          <div className="terminal-header">
            <div className="terminal-dot red" />
            <div className="terminal-dot yellow" />
            <div className="terminal-dot green" />
            <span className="terminal-title">system output</span>
          </div>
          <div className="terminal-body">
            {messages.map((m, i) => (
              <div key={i} className={`terminal-line ${m.startsWith('✓') ? 'line-success' : m.startsWith('✗') ? 'line-error' : ''}`}>
                <span className="terminal-prompt">›</span> {m}
              </div>
            ))}
          </div>
        </div>

        {phase === 'review' && preview && (
          <div className="startup-review-panel">
            <div className="startup-review-intro">
              <strong>Review required</strong>
              <span>{preview?.has_changes ? 'Review every pending revision below. Nothing will be changed until you approve it.' : 'Only revision bookkeeping is pending. Approval records the revisions without running migration operations.'}</span>
            </div>
            <div className="startup-review-meta">
              <span>Revision: {preview.revision || 'unknown'}</span>
              <span>File: {preview.filename || 'unknown'}</span>
            </div>
            {operationError && <div className="startup-notice startup-notice-error" role="alert">{operationError}</div>}
            <div className="startup-review-actions">
              <button
                ref={primaryReviewActionRef}
                type="button"
                className="startup-btn startup-btn-primary"
                disabled={busy}
                onClick={() => { void applyMigration(); }}
              >
                Apply migration
              </button>
              <button
                type="button"
                className="startup-btn startup-btn-secondary"
                disabled={busy}
                onClick={() => { void regenerateMigration(); }}
              >
                Generate preview again
              </button>
              <button
                type="button"
                className="startup-btn startup-btn-danger"
                disabled={busy}
                onClick={() => { void discardMigration(); }}
              >
                Skip for this startup
              </button>
            </div>
            <pre className="startup-diff">{preview.diff || '# No diff available'}</pre>
          </div>
        )}
      </div>
    </div>
  );
}
