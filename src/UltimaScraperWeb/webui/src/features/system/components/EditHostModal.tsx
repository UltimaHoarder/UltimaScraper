import { useEffect, useState, type FormEvent } from 'react';

import { listDeployments, operateDeployment, type ClusterHost, type Deployment } from '../../../api/webui';
import { RunLog } from '../../connections/RunLog';
import { useInstallRun } from '../../connections/lib/useInstallRun';

type Service = 'backend' | 'worker' | 'webui';

const SERVICES: { id: Service; label: string; hint: string }[] = [
  { id: 'backend', label: 'Backend', hint: 'The API: this WebUI connects to it.' },
  { id: 'worker', label: 'Workers', hint: 'Run scrape and download jobs for the cluster.' },
  { id: 'webui', label: 'WebUI', hint: 'A WebUI of its own on this host, over HTTPS.' },
];

const enabled = (value: unknown) => value === true || value === 'install';

/**
 * Change which services a host runs, in the install this WebUI made there:
 * turn the backend, workers or a WebUI on or off. PostgreSQL and Redis stay
 * as they were installed.
 */
export function EditHostModal({
  host,
  onClose,
  onChanged,
}: {
  host: ClusterHost;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [deployment, setDeployment] = useState<Deployment | null>(null);
  const [loadError, setLoadError] = useState('');
  const [wanted, setWanted] = useState<Record<Service, boolean>>({ backend: false, worker: false, webui: false });
  const [authMethod, setAuthMethod] = useState<'password' | 'key'>('password');
  const [password, setPassword] = useState('');
  const [privateKey, setPrivateKey] = useState('');
  const [sudoPassword, setSudoPassword] = useState('');
  const [error, setError] = useState('');
  const [runId, setRunId] = useState<string | null>(null);
  const { status, events } = useInstallRun(runId);
  const finished = status !== null && status.state !== 'running';

  useEffect(() => {
    let active = true;
    listDeployments().then(
      (loaded) => {
        if (!active) return;
        const found = loaded.find((item) => item.id === host.deployment_id) ?? null;
        setDeployment(found);
        const components = found?.details.components;
        if (components) {
          setWanted({
            backend: enabled(components.backend),
            worker: enabled(components.worker),
            webui: enabled(components.webui),
          });
        }
        if (!found) setLoadError('This WebUI has no install on this host to change.');
      },
      (failure) => active && setLoadError(failure instanceof Error ? failure.message : 'Could not read the install.'),
    );
    return () => {
      active = false;
    };
  }, [host.deployment_id]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  useEffect(() => {
    if (finished && status?.state === 'succeeded') onChanged();
    // Once, when the run ends.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [finished]);

  const ssh = deployment?.details.kind === 'ssh';
  const components = deployment?.details.components;
  const changed =
    components !== undefined &&
    (wanted.backend !== enabled(components.backend) ||
      wanted.worker !== enabled(components.worker) ||
      wanted.webui !== enabled(components.webui));

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!deployment) return;
    setError('');
    try {
      const started = await operateDeployment(deployment.id, {
        action: 'services',
        services: wanted,
        credentials: {
          password: ssh && authMethod === 'password' ? password : undefined,
          private_key: ssh && authMethod === 'key' ? privateKey : undefined,
          sudo_password: sudoPassword || undefined,
        },
      });
      setRunId(started.id);
    } catch (startError) {
      setError(startError instanceof Error ? startError.message : 'The change did not start.');
    }
  };

  const stores = [
    ['PostgreSQL', components?.postgres],
    ['Redis', components?.redis],
  ] as const;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <section
        className="modal-content fleet-register-inspect-modal edit-host-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="edit-host-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <span className="fleet-register-kicker">Edit host</span>
            <h3 id="edit-host-title">{host.name}</h3>
          </div>
          <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          {runId ? (
            <div className="deployment-panel">
              <RunLog events={events} />
              {finished && (
                <div className="connections-actions">
                  <button type="button" className="fleet-register-button" onClick={onClose}>
                    Close
                  </button>
                </div>
              )}
            </div>
          ) : (
            <form className="connections-form" onSubmit={submit}>
              {loadError && (
                <p className="connections-error" role="alert">
                  {loadError}
                </p>
              )}
              {deployment && (
                <>
                  <p className="connections-copy">
                    The services {host.name} runs, in the install at <code>{deployment.details.install_dir}</code>.
                    Turning one off stops it; its data stays.
                  </p>
                  <fieldset className="edit-host-services">
                    <legend>Services</legend>
                    {SERVICES.map((service) => (
                      <label key={service.id} className="connections-checkbox">
                        <input
                          type="checkbox"
                          checked={wanted[service.id]}
                          onChange={(event) => setWanted((current) => ({ ...current, [service.id]: event.target.checked }))}
                        />
                        <span>
                          <strong>{service.label}</strong> · {service.hint}
                        </span>
                      </label>
                    ))}
                    {stores.map(([label, mode]) => (
                      <p key={label} className="connections-hint">
                        {label}: {enabled(mode) ? 'installed here, and stays' : 'not on this host'}
                      </p>
                    ))}
                  </fieldset>
                  {ssh && (
                    <>
                      <div className="deploy-choice">
                        <label className="connections-checkbox">
                          <input type="radio" checked={authMethod === 'password'} onChange={() => setAuthMethod('password')} />
                          <span>SSH password</span>
                        </label>
                        <label className="connections-checkbox">
                          <input type="radio" checked={authMethod === 'key'} onChange={() => setAuthMethod('key')} />
                          <span>Private key</span>
                        </label>
                      </div>
                      {authMethod === 'password' ? (
                        <label>
                          <span>
                            Password for {deployment.details.username}@{deployment.details.host}
                          </span>
                          <input
                            type="password"
                            value={password}
                            onChange={(event) => setPassword(event.target.value)}
                            autoComplete="off"
                            required
                          />
                        </label>
                      ) : (
                        <label>
                          <span>Private key</span>
                          <textarea
                            rows={4}
                            value={privateKey}
                            onChange={(event) => setPrivateKey(event.target.value)}
                            spellCheck={false}
                            required
                          />
                        </label>
                      )}
                    </>
                  )}
                  <label>
                    <span>sudo password (optional; only where Docker needs it)</span>
                    <input
                      type="password"
                      value={sudoPassword}
                      onChange={(event) => setSudoPassword(event.target.value)}
                      autoComplete="off"
                    />
                  </label>
                </>
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
                  disabled={!deployment || !changed}
                >
                  Apply
                </button>
                <button type="button" className="fleet-register-button" onClick={onClose}>
                  Cancel
                </button>
              </div>
            </form>
          )}
        </div>
      </section>
    </div>
  );
}
