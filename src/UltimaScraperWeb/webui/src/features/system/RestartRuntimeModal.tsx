import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { RuntimeServiceTarget } from '../../api/types/system';
import './RestartRuntimeModal.css';

export interface RuntimeServiceOption {
  id: RuntimeServiceTarget;
  label: string;
  tag: string;
  description: string;
  impact: string;
}

const RUNTIME_SERVICES: readonly RuntimeServiceOption[] = [
  {
    id: 'api',
    label: 'API & Control Plane',
    tag: 'CORE',
    description: 'REST endpoints, WebSocket event streams, and supervisor coordination.',
    impact: 'Web UI briefly disconnects and reconnects once the control plane is live.',
  },
  {
    id: 'database_writer',
    label: 'Database Writer',
    tag: 'DATA',
    description: 'Processes persistent write queues and transactional database records.',
    impact: 'Write operations pause briefly and resume with zero data loss.',
  },
  {
    id: 'worker_pool',
    label: 'Worker Pool',
    tag: 'EXECUTION',
    description: 'Active download workers, scrapers, and pipeline jobs.',
    impact: 'Running tasks are interrupted and resume from their last checkpoint.',
  },
  {
    id: 'plugins',
    label: 'Plugin Supervisor',
    tag: 'EXTENSIONS',
    description: 'External extensions, hooks, and lifecycle listeners.',
    impact: 'Active plugin scripts and socket channels cycle cleanly.',
  },
  {
    id: 'webui',
    label: 'Web UI',
    tag: 'INTERFACE',
    description: 'Local web server and frontend asset server.',
    impact: 'Reloads dashboard assets and reconnects active client sessions.',
  },
];

export interface RestartRuntimeModalProps {
  isOpen: boolean;
  isPending?: boolean;
  onClose: () => void;
  onConfirm: (targets: RuntimeServiceTarget[]) => void;
}

export function RestartRuntimeModal({
  isOpen,
  isPending = false,
  onClose,
  onConfirm,
}: RestartRuntimeModalProps) {
  const id = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<Set<RuntimeServiceTarget>>(
    () => new Set(RUNTIME_SERVICES.map((s) => s.id)),
  );

  // Reset to all selected each time it opens (adjusted while rendering, not in an effect).
  const [wasOpen, setWasOpen] = useState(isOpen);
  if (isOpen !== wasOpen) {
    setWasOpen(isOpen);
    if (isOpen) setSelected(new Set(RUNTIME_SERVICES.map((s) => s.id)));
  }

  // Trap focus and handle escape
  useEffect(() => {
    if (!isOpen) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        if (!isPending) onClose();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusables = dialogRef.current?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled)',
      );
      if (!focusables || focusables.length === 0) {
        event.preventDefault();
        dialogRef.current?.focus();
        return;
      }
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialogRef.current)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', handleKeyDown, true);
    return () => {
      document.removeEventListener('keydown', handleKeyDown, true);
      document.body.style.overflow = overflow;
      if (previous?.isConnected) previous.focus();
    };
  }, [isOpen, isPending, onClose]);

  const allSelected = selected.size === RUNTIME_SERVICES.length;
  const isApiSelected = selected.has('api');

  const toggleService = (serviceId: RuntimeServiceTarget) => {
    if (isPending) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(serviceId)) {
        next.delete(serviceId);
      } else {
        next.add(serviceId);
      }
      return next;
    });
  };

  const selectAll = () => {
    if (isPending) return;
    setSelected(new Set(RUNTIME_SERVICES.map((s) => s.id)));
  };

  const selectWorkersAndPlugins = () => {
    if (isPending) return;
    setSelected(new Set<RuntimeServiceTarget>(['worker_pool', 'plugins']));
  };

  const selectWebUiOnly = () => {
    if (isPending) return;
    setSelected(new Set<RuntimeServiceTarget>(['webui']));
  };

  const clearAll = () => {
    if (isPending) return;
    setSelected(new Set());
  };

  const confirmLabel = useMemo(() => {
    if (isPending) return 'Restarting…';
    if (allSelected) return 'Restart runtime';
    if (selected.size === 0) return 'Select services';
    return `Restart selected (${selected.size})`;
  }, [allSelected, isPending, selected.size]);

  if (!isOpen) return null;

  return createPortal(
    <div
      className="confirm-dialog__overlay atlas-confirm-overlay restart-modal-overlay"
      onClick={() => {
        if (!isPending) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className="confirm-dialog atlas-confirm restart-runtime-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        aria-describedby={`${id}-desc`}
        tabIndex={-1}
        aria-busy={isPending}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="atlas-confirm__classification atlas-confirm__classification--danger">
          SYSTEM CONTROL / CONFIRMATION
        </div>

        <h2 id={`${id}-title`} className="confirm-dialog__title">
          Restart UltimaScraper?
        </h2>

        <p id={`${id}-desc`} className="confirm-dialog__description">
          Stop the API, database writer, worker pool, plugins and this web UI, then start them again. Running tasks are interrupted and resume from their last checkpoint.
        </p>

        <div className="restart-runtime-presets" role="toolbar" aria-label="Restart presets">
          <span className="restart-preset-label">Presets:</span>
          <button
            type="button"
            className={`restart-preset-btn ${allSelected ? 'is-active' : ''}`}
            onClick={selectAll}
            disabled={isPending}
          >
            All services
          </button>
          <button
            type="button"
            className="restart-preset-btn"
            onClick={selectWorkersAndPlugins}
            disabled={isPending}
          >
            Workers & Plugins
          </button>
          <button
            type="button"
            className="restart-preset-btn"
            onClick={selectWebUiOnly}
            disabled={isPending}
          >
            Web UI only
          </button>
          <button
            type="button"
            className="restart-preset-btn restart-preset-btn--clear"
            onClick={clearAll}
            disabled={isPending}
          >
            Clear
          </button>
        </div>

        <div className="restart-services-list" role="group" aria-label="Services to restart">
          {RUNTIME_SERVICES.map((service) => {
            const isChecked = selected.has(service.id);
            return (
              <label
                key={service.id}
                className={`restart-service-card ${isChecked ? 'is-selected' : ''}`}
              >
                <input
                  type="checkbox"
                  className="restart-service-checkbox"
                  checked={isChecked}
                  onChange={() => toggleService(service.id)}
                  disabled={isPending}
                  aria-label={`Restart ${service.label}`}
                />
                <div className="restart-service-info">
                  <div className="restart-service-header">
                    <span className="restart-service-title">{service.label}</span>
                    <span className="restart-service-tag">{service.tag}</span>
                  </div>
                  <div className="restart-service-description">{service.description}</div>
                  <div className="restart-service-impact">Impact: {service.impact}</div>
                </div>
              </label>
            );
          })}
        </div>

        <div
          className={`restart-mode-banner ${
            selected.size === 0
              ? 'is-empty'
              : isApiSelected
              ? 'is-full'
              : 'is-targeted'
          }`}
          role="status"
        >
          {selected.size === 0 ? (
            <span>Select at least one service to proceed with restart.</span>
          ) : isApiSelected ? (
            <span>
              <strong>Core restart:</strong> Includes API control plane. The supervisor will cycle services and reconnect the web interface.
            </span>
          ) : (
            <span>
              <strong>Targeted service restart:</strong> API and Web UI remain uninterrupted. Only the selected background workers will cycle.
            </span>
          )}
        </div>

        <div className="confirm-dialog__actions">
          <button
            type="button"
            className="confirm-dialog__button"
            onClick={onClose}
            disabled={isPending}
          >
            Cancel
          </button>
          <button
            type="button"
            className="confirm-dialog__button confirm-dialog__button--danger"
            onClick={() => {
              if (selected.size > 0 && !isPending) {
                onConfirm(Array.from(selected));
              }
            }}
            disabled={selected.size === 0 || isPending}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
