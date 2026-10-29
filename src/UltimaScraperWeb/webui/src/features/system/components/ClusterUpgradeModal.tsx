import { useEffect, useState, type FormEvent, type ReactNode } from 'react';

import { listClusterDeployments, upgradeCluster, type ClusterUpgrade, type Deployment } from '../../../api/webui';
import { RunLog } from '../../connections/RunLog';
import { useInstallRun } from '../../connections/lib/useInstallRun';
import { DEFAULT_IMAGE_REGISTRY, normalizeImagePrefix } from '../../setup-wizard/lib/imageVersion';

type Auth = { method: 'password' | 'key'; password: string; privateKey: string };

const EMPTY_AUTH: Auth = { method: 'password', password: '', privateKey: '' };

function SshFields({ label, auth, onChange }: { label: string; auth: Auth; onChange: (auth: Auth) => void }) {
  return (
    <fieldset className="cluster-upgrade-host">
      <legend>{label}</legend>
      <div className="deploy-choice">
        <label className="connections-checkbox">
          <input type="radio" checked={auth.method === 'password'} onChange={() => onChange({ ...auth, method: 'password' })} />
          <span>SSH password</span>
        </label>
        <label className="connections-checkbox">
          <input type="radio" checked={auth.method === 'key'} onChange={() => onChange({ ...auth, method: 'key' })} />
          <span>Private key</span>
        </label>
      </div>
      {auth.method === 'password' ? (
        <label>
          <span>Password for {label}</span>
          <input
            type="password"
            value={auth.password}
            onChange={(event) => onChange({ ...auth, password: event.target.value })}
            autoComplete="off"
            required
          />
        </label>
      ) : (
        <label>
          <span>Private key for {label}</span>
          <textarea
            rows={4}
            value={auth.privateKey}
            onChange={(event) => onChange({ ...auth, privateKey: event.target.value })}
            spellCheck={false}
            required
          />
        </label>
      )}
    </fieldset>
  );
}

function UpgradeModal({ children, onClose }: { children: ReactNode; onClose: () => void }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="modal-overlay" onClick={onClose}>
      <section
        className="modal-content fleet-register-inspect-modal cluster-upgrade-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="cluster-upgrade-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <span className="fleet-register-kicker">Cluster</span>
            <h3 id="cluster-upgrade-title">Upgrade cluster</h3>
          </div>
          <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </section>
    </div>
  );
}

const sshLabel = (deployment: Deployment) =>
  `${deployment.details.username ? `${deployment.details.username}@` : ''}${deployment.details.host ?? deployment.target}`;

/**
 * Upgrades every deployment this WebUI manages in the cluster to one version,
 * one after another: API servers first, as they bring the shared database up
 * to date. A failed upgrade rolls back its own node and stops the rest.
 */
export function ClusterUpgradeModal({ clusterId, onClose }: { clusterId: string; onClose: () => void }) {
  const [deployments, setDeployments] = useState<Deployment[] | null>(null);
  const [loadError, setLoadError] = useState('');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [version, setVersion] = useState('');
  const [imageSource, setImageSource] = useState<'' | Deployment['details']['image_source']>('');
  const [imagePrefix, setImagePrefix] = useState('');
  const [sameAuth, setSameAuth] = useState(true);
  const [sharedAuth, setSharedAuth] = useState<Auth>(EMPTY_AUTH);
  const [auths, setAuths] = useState<Record<string, Auth>>({});
  const [sudoPassword, setSudoPassword] = useState('');
  const [error, setError] = useState('');
  const [runId, setRunId] = useState<string | null>(null);
  const { status, events } = useInstallRun(runId);
  const finished = status !== null && status.state !== 'running';

  useEffect(() => {
    let active = true;
    listClusterDeployments(clusterId).then(
      (loaded) => {
        if (!active) return;
        setDeployments(loaded);
        setSelected(new Set(loaded.map((item) => item.id)));
        // Re-pulling the running tag (such as edge) is the usual upgrade.
        setVersion(loaded[0]?.details.version ?? '');
      },
      (failure) => active && setLoadError(failure instanceof Error ? failure.message : 'Could not list the deployments.'),
    );
    return () => {
      active = false;
    };
  }, [clusterId]);

  const chosen = (deployments ?? []).filter((item) => selected.has(item.id));
  const sshChosen = chosen.filter((item) => item.details.kind === 'ssh');
  const shared = sameAuth && sshChosen.length > 1;

  const credentialsFor = (auth: Auth) =>
    auth.method === 'password' ? { password: auth.password } : { private_key: auth.privateKey };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    const credentials: ClusterUpgrade['credentials'] = {};
    for (const item of chosen) {
      const sudo = sudoPassword ? { sudo_password: sudoPassword } : {};
      credentials[item.id] =
        item.details.kind === 'ssh'
          ? { ...credentialsFor(shared ? sharedAuth : (auths[item.id] ?? EMPTY_AUTH)), ...sudo }
          : sudo;
    }
    try {
      const started = await upgradeCluster(clusterId, {
        version: version.trim(),
        image_source: imageSource || undefined,
        image_prefix: imageSource === 'registry' ? normalizeImagePrefix(imagePrefix) || undefined : undefined,
        credentials,
        deployment_ids: chosen.map((item) => item.id),
      });
      setRunId(started.id);
    } catch (startError) {
      setError(startError instanceof Error ? startError.message : 'The upgrade did not start.');
    }
  };

  if (runId) {
    return (
      <UpgradeModal onClose={onClose}>
        <div className="deployment-panel cluster-upgrade-panel" aria-label="Cluster upgrade">
          {!finished && (
            <p className="connections-hint">Closing this does not stop the upgrade.</p>
          )}
          <RunLog events={events} />
          {finished && (
            <div className="connections-actions">
              <button type="button" className="fleet-register-button" onClick={onClose}>
                Close
              </button>
            </div>
          )}
        </div>
      </UpgradeModal>
    );
  }

  return (
    <UpgradeModal onClose={onClose}>
    <form className="connections-form deployment-panel cluster-upgrade-panel" aria-label="Upgrade cluster" onSubmit={submit}>
      <p className="connections-copy">
        Upgrades each node below to one version, one after another, API servers first. If one fails, it goes back to
        its version and the rest are left as they are.
      </p>
      {loadError && <p className="connections-error" role="alert">{loadError}</p>}
      {deployments && deployments.length === 0 && (
        <p className="connections-hint">
          This WebUI installed none of this cluster&apos;s nodes, so it cannot upgrade them. Nodes installed elsewhere
          are upgraded where they were installed.
        </p>
      )}
      {deployments && deployments.length > 0 && (
        <>
          <ul className="cluster-upgrade-list">
            {deployments.map((item) => (
              <li key={item.id}>
                <label className="connections-checkbox">
                  <input
                    type="checkbox"
                    checked={selected.has(item.id)}
                    onChange={(event) =>
                      setSelected((current) => {
                        const next = new Set(current);
                        if (event.target.checked) next.add(item.id);
                        else next.delete(item.id);
                        return next;
                      })
                    }
                  />
                  <span>
                    <strong>{item.name}</strong> · {item.details.kind === 'ssh' ? sshLabel(item) : 'this machine'} ·{' '}
                    <code>{item.details.version}</code>
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <div className="deploy-row">
            <label>
              <span>Images</span>
              <select value={imageSource} onChange={(event) => setImageSource(event.target.value as typeof imageSource)}>
                <option value="">Where each node got them</option>
                <option value="copy">Copy from this server</option>
                <option value="target">Already on the hosts</option>
                <option value="registry">Pull from a registry</option>
              </select>
            </label>
            <label className="deploy-port">
              <span>Version</span>
              <input value={version} onChange={(event) => setVersion(event.target.value)} placeholder="0.2.0" required />
            </label>
          </div>
          {imageSource === 'registry' && (
            <label>
              <span>Registry</span>
              <input value={imagePrefix} onChange={(event) => setImagePrefix(event.target.value)} placeholder={DEFAULT_IMAGE_REGISTRY} />
            </label>
          )}
          {sshChosen.length > 1 && (
            <label className="connections-checkbox">
              <input type="checkbox" checked={sameAuth} onChange={(event) => setSameAuth(event.target.checked)} />
              <span>Use the same SSH credentials for every host</span>
            </label>
          )}
          {shared ? (
            <SshFields label={sshChosen.map(sshLabel).join(', ')} auth={sharedAuth} onChange={setSharedAuth} />
          ) : (
            sshChosen.map((item) => (
              <SshFields
                key={item.id}
                label={sshLabel(item)}
                auth={auths[item.id] ?? EMPTY_AUTH}
                onChange={(auth) => setAuths((current) => ({ ...current, [item.id]: auth }))}
              />
            ))
          )}
          <label>
            <span>sudo password (optional; only where Docker needs it)</span>
            <input type="password" value={sudoPassword} onChange={(event) => setSudoPassword(event.target.value)} autoComplete="off" />
          </label>
        </>
      )}
      {error && <p className="connections-error" role="alert">{error}</p>}
      <div className="connections-actions">
        <button
          type="submit"
          className="fleet-register-button fleet-register-button--primary"
          disabled={chosen.length === 0 || !version.trim()}
        >
          Upgrade {chosen.length} node{chosen.length === 1 ? '' : 's'}
        </button>
        <button type="button" className="fleet-register-button" onClick={onClose}>
          Cancel
        </button>
      </div>
    </form>
    </UpgradeModal>
  );
}
