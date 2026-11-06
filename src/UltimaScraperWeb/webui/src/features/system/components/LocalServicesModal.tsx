import { useEffect, useState, type FormEvent } from 'react';

import {
  getLocalServices,
  setLocalServices,
  type ClusterHost,
  type LocalServiceName,
  type LocalServices,
} from '../../../api/webui';

const SERVICES: { id: LocalServiceName; label: string; hint: string }[] = [
  { id: 'backend', label: 'Backend', hint: 'The API. Other machines reach it on port 21121 if this app publishes it.' },
  { id: 'worker', label: 'Workers', hint: 'Run scrape and download jobs for the cluster.' },
];

const STATE_LABELS = { running: 'Running', restarting: 'Restarting', stopped: 'Stopped' } as const;

// While the dialog is open, so a service's start shows without reopening it.
const REFRESH_MS = 3000;

/**
 * Turn the backend and workers on or off in this WebUI's own container: for a
 * WebUI that runs alone, as a NAS app does. They use the cluster's PostgreSQL,
 * Redis and secret key, which a backend of the cluster gives.
 */
export function LocalServicesModal({
  host,
  clusterId,
  onClose,
  onChanged,
}: {
  host: ClusterHost;
  clusterId: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [current, setCurrent] = useState<LocalServices | null>(null);
  const [loadError, setLoadError] = useState('');
  const [wanted, setWanted] = useState<Record<LocalServiceName, boolean>>({ backend: false, worker: false });
  const [address, setAddress] = useState(host.address ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    let first = true;
    const load = () =>
      getLocalServices().then(
        (loaded) => {
          if (!active) return;
          setCurrent(loaded);
          if (first) {
            first = false;
            setWanted({ backend: loaded.backend, worker: loaded.worker });
            if (loaded.advertise_host) setAddress(loaded.advertise_host);
          }
        },
        (failure) => active && setLoadError(failure instanceof Error ? failure.message : 'Could not read the services.'),
      );
    void load();
    const timer = window.setInterval(() => void load(), REFRESH_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const changed =
    current !== null &&
    (wanted.backend !== current.backend ||
      wanted.worker !== current.worker ||
      ((wanted.backend || wanted.worker) && address.trim() !== (current.advertise_host ?? '')));

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    setSaving(true);
    try {
      setCurrent(
        await setLocalServices({
          cluster_id: clusterId,
          backend: wanted.backend,
          worker: wanted.worker,
          advertise_host: address.trim() || null,
        }),
      );
      onChanged();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : 'The services could not be changed.');
    } finally {
      setSaving(false);
    }
  };

  const running = current?.services.filter((service) => current[service.name] || service.state !== 'stopped') ?? [];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <section
        className="modal-content fleet-register-inspect-modal edit-host-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="local-services-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <span className="fleet-register-kicker">Edit host</span>
            <h3 id="local-services-title">{host.name}</h3>
          </div>
          <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          <form className="connections-form" onSubmit={submit}>
            {loadError && (
              <p className="connections-error" role="alert">
                {loadError}
              </p>
            )}
            {current && !current.available && (
              <p className="connections-error" role="alert">
                This WebUI cannot run the backend or workers: it does not run from the full UltimaScraper image.
              </p>
            )}
            {current?.available && (
              <>
                <p className="connections-copy">
                  This WebUI runs them in its own container, with the cluster&apos;s PostgreSQL, Redis and secret key.
                  They start again with it. Turning one off stops it; the cluster&apos;s data stays.
                </p>
                <fieldset className="edit-host-services">
                  <legend>Services</legend>
                  {SERVICES.map((service) => (
                    <label key={service.id} className="connections-checkbox">
                      <input
                        type="checkbox"
                        checked={wanted[service.id]}
                        disabled={saving}
                        onChange={(event) => setWanted((value) => ({ ...value, [service.id]: event.target.checked }))}
                      />
                      <span>
                        <strong>{service.label}</strong> · {service.hint}
                      </span>
                    </label>
                  ))}
                </fieldset>
                {(wanted.backend || wanted.worker) && (
                  <>
                    <label>
                      <span>This machine&apos;s address on its network</span>
                      <input
                        value={address}
                        disabled={saving}
                        onChange={(event) => setAddress(event.target.value)}
                        placeholder="192.168.1.20"
                        spellCheck={false}
                      />
                    </label>
                    <p className="connections-hint">
                      A container cannot see it. The cluster lists these services under it, and other machines reach
                      the backend there.
                    </p>
                  </>
                )}
                {wanted.worker && (
                  <p className="connections-hint">
                    Workers save media to the folders in the cluster&apos;s storage settings, so mount those folders
                    into this app.
                  </p>
                )}
              </>
            )}
            {running.length > 0 && (
              <div className="local-services-status" aria-label="Service status">
                {running.map((service) => (
                  <details key={service.name}>
                    <summary>
                      <strong>{service.name === 'backend' ? 'Backend' : 'Workers'}</strong>:{' '}
                      {STATE_LABELS[service.state]}
                      {service.state !== 'running' && service.exit_code !== null && ` (exited with ${service.exit_code})`}
                    </summary>
                    <pre className="admin-token-command">
                      <code>{service.log.slice(-40).join('\n') || 'No output yet.'}</code>
                    </pre>
                  </details>
                ))}
              </div>
            )}
            {error && (
              <p className="connections-error" role="alert">
                {error}
              </p>
            )}
            <div className="connections-actions">
              <button
                type="submit"
                className="fleet-register-button fleet-register-button--primary"
                disabled={!current?.available || !changed || saving}
              >
                {saving ? 'Applying…' : 'Apply'}
              </button>
              <button type="button" className="fleet-register-button" onClick={onClose}>
                Close
              </button>
            </div>
          </form>
        </div>
      </section>
    </div>
  );
}
