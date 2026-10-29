import { useEffect, useState } from 'react';

import { ClusterInviteResult } from '../../connections/ClusterInviteResult';
import { useClusterInvite } from '../../connections/lib/useClusterInvite';

function Action({ title, text, onClick }: { title: string; text: string; onClick: () => void }) {
  return (
    <button type="button" className="add-host-choice" onClick={onClick}>
      <strong>{title}</strong>
      <span>{text}</span>
    </button>
  );
}

/** What can be done to a cluster as a whole, in one place. */
export function ManageClusterModal({
  clusterId,
  clusterName,
  isMain,
  onMakeMain,
  onAddHost,
  onUpgrade,
  onClose,
}: {
  clusterId: string;
  clusterName: string;
  isMain: boolean;
  onMakeMain: () => void;
  onAddHost: () => void;
  onUpgrade: () => void;
  onClose: () => void;
}) {
  const [inviting, setInviting] = useState(false);
  const invite = useClusterInvite(clusterId);

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
        className="modal-content fleet-register-inspect-modal add-host-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="manage-cluster-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <span className="fleet-register-kicker">Manage cluster</span>
            <h3 id="manage-cluster-title">{clusterName}</h3>
          </div>
          <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          {inviting ? (
            <div className="connections-form">
              <button type="button" className="fleet-register-link add-host-back" onClick={() => setInviting(false)}>
                ← Other actions
              </button>
              <ol className="add-host-steps">
                <li>Copy an invite for {clusterName}.</li>
                <li>
                  On the other WebUI, open <strong>Set up</strong>, choose <strong>Join a cluster</strong> and paste it.
                </li>
                <li>It appears under its host once it checks in.</li>
              </ol>
              <div className="connections-actions">
                <button
                  type="button"
                  className="fleet-register-button fleet-register-button--primary"
                  onClick={() => void invite.copy()}
                >
                  Copy invite
                </button>
              </div>
              <ClusterInviteResult invite={invite.invite} error={invite.error} />
            </div>
          ) : (
            <div className="add-host-choices">
              <Action
                title="Add host"
                text="Install a backend or workers on a local or remote host, or connect a running backend."
                onClick={onAddHost}
              />
              <Action
                title="Invite a WebUI"
                text="Copy a one-time invite another WebUI joins this cluster with."
                onClick={() => setInviting(true)}
              />
              <Action
                title="Upgrade cluster"
                text="Move the hosts this WebUI installed to one version, one after another."
                onClick={onUpgrade}
              />
              {!isMain && (
                <Action
                  title="Make main"
                  text="Open this WebUI on this cluster, for everyone who signs in."
                  onClick={onMakeMain}
                />
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
