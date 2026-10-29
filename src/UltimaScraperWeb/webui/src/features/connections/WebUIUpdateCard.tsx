import { useEffect, useState } from 'react';

import { getWebUISession, getWebUIUpdate, updateWebUI, type WebUIUpdateStatus } from '../../api/webui';

const RESTART_POLL_MS = 2000;
const RESTART_TIMEOUT_MS = 120_000;

/** Waits for the restarted WebUI to answer, then reloads onto the new version. */
async function waitForRestart(): Promise<boolean> {
  const deadline = Date.now() + RESTART_TIMEOUT_MS;
  // The old process answers until it restarts; give it time to go away first.
  await new Promise((resolve) => setTimeout(resolve, RESTART_POLL_MS));
  while (Date.now() < deadline) {
    try {
      await getWebUISession();
      return true;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, RESTART_POLL_MS));
    }
  }
  return false;
}

/** This WebUI's version, with an update button when a newer one is published. */
export function WebUIUpdateCard({ reload = () => window.location.reload() }: { reload?: () => void }) {
  const [status, setStatus] = useState<WebUIUpdateStatus | null>(null);
  const [phase, setPhase] = useState<'idle' | 'updating' | 'restarting' | 'failed'>('idle');
  const [message, setMessage] = useState('');

  useEffect(() => {
    let active = true;
    getWebUIUpdate()
      .then((loaded) => active && setStatus(loaded))
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  if (!status) return null;

  const update = async () => {
    setPhase('updating');
    setMessage('');
    try {
      const result = await updateWebUI();
      setPhase('restarting');
      setMessage(`Installed ${result.version}. Restarting…`);
      if (await waitForRestart()) {
        reload();
      } else {
        setPhase('failed');
        setMessage(`Installed ${result.version}, but the WebUI has not come back. Check its log.`);
      }
    } catch (updateError) {
      setPhase('failed');
      setMessage(updateError instanceof Error ? updateError.message : 'The update failed.');
    }
  };

  return (
    <section className="webui-update" aria-label="WebUI version">
      <div className="connections-row-main">
        <strong>WebUI</strong>
        <span className="connections-tag" title="The installed WebUI version">
          {status.version || 'unknown'}
        </span>
        <span className="connections-tag" title="Which builds this WebUI updates to">
          {status.channel}
        </span>
        {status.update_available && status.latest && (
          <span className="connections-status is-pending">{status.latest} is available</span>
        )}
        {!status.update_available && status.latest && !status.reason && (
          <span className="connections-status is-ok">✓ Up to date</span>
        )}
      </div>
      {status.reason && phase === 'idle' && <p className="connections-hint">{status.reason}</p>}
      {!status.reason && !status.latest && phase === 'idle' && (
        <p className="connections-hint">Nothing has been published to the package index yet.</p>
      )}
      {message && (
        <p className={phase === 'failed' ? 'connections-error' : 'connections-hint'} role={phase === 'failed' ? 'alert' : 'status'}>
          {message}
        </p>
      )}
      {status.can_update && status.latest && (
        <div className="connections-actions">
          <button
            type="button"
            className="connections-button is-primary"
            disabled={phase === 'updating' || phase === 'restarting'}
            onClick={() => void update()}
          >
            {phase === 'updating' ? 'Updating…' : phase === 'restarting' ? 'Restarting…' : `Update to ${status.latest}`}
          </button>
        </div>
      )}
    </section>
  );
}
