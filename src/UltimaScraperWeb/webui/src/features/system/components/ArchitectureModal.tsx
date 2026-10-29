import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';

import { getSettings } from '../../../api/settings';
import { ArchitectureDiagram } from '../../setup-wizard/ArchitectureDiagram';
import { buildActiveMounts } from '../lib/architectureStorage';
import type { RegisterBackend } from '../systemFleetRegisterData';
import './ArchitectureModal.css';

/** The whole system at a glance: WebUIs, clusters, hosts, services and storage, and how a download moves through them. */
export function ArchitectureModal({ backends, onClose }: { backends: RegisterBackend[]; onClose: () => void }) {
  const settingsQuery = useQuery({ queryKey: ['settings'], queryFn: getSettings });

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const storage = buildActiveMounts(backends, settingsQuery.data?.download_setup?.staging_directories);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <section
        className="modal-content modal-content--wide fleet-register-inspect-modal architecture-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="architecture-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <div>
            <span className="fleet-register-kicker">Clusters</span>
            <h3 id="architecture-title">Architecture</h3>
          </div>
          <button type="button" className="modal-close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          <ArchitectureDiagram storage={storage} />
        </div>
      </section>
    </div>
  );
}
