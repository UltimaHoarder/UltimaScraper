import { useSearchParams } from 'react-router-dom';
import { useDrivesMockModel } from './drivesMockModel';
import { DriveCockpitConcept } from './DriveCockpitConcept';
import { DualPaneStudioConcept } from './DualPaneStudioConcept';
import { StoragePipelineConcept } from './StoragePipelineConcept';
import { CapacityCommanderConcept } from './CapacityCommanderConcept';
import { DriveStudioProConcept } from './DriveStudioProConcept';
import './DrivesRedesignsMock.css';

export const DRIVE_CONCEPTS = [
  {
    id: 'cockpit',
    name: 'Storage Cockpit Console',
    note: 'Operations-first, high-density command console with multi-segment partition bars, mount telemetry, and fast inline directory lifecycle controls.',
  },
  {
    id: 'dualpane',
    name: 'Dual-Pane Storage Architect',
    note: 'Master-detail split pane keeping drive telemetry and directory inventory in sight while editing policies or live-testing token resolution.',
  },
  {
    id: 'pipeline',
    name: 'Visual Flow & Ingestion Pipeline',
    note: 'Interactive node pipeline tracking assets from worker staging buffers through capacity gates to primary and overflow spillways.',
  },
  {
    id: 'capacity',
    name: 'Capacity & Quota Commander',
    note: 'Tier-based storage governor featuring dynamic watermark sliders, predictive retention runway, and sticky batch directory operations.',
  },
  {
    id: 'pro',
    name: 'Drive Studio Pro & Diagnostics',
    note: 'Comprehensive 4-tab control center with synthetic I/O benchmarking, interactive clickable token palette, and worker sync audit.',
  },
] as const;

export type DriveConceptId = typeof DRIVE_CONCEPTS[number]['id'];

export function DrivesRedesignsMock() {
  const model = useDrivesMockModel();
  const [params, setParams] = useSearchParams();

  const activeId = (params.get('concept') as DriveConceptId) || DRIVE_CONCEPTS[0].id;
  const activeConcept = DRIVE_CONCEPTS.find((c) => c.id === activeId) ?? DRIVE_CONCEPTS[0];

  const selectConcept = (id: string) => {
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.set('category', 'drives');
      next.set('concept', id);
      return next;
    });
    window.scrollTo({ top: 0, behavior: 'instant' });
  };

  return (
    <div className="dm-lab">
      {/* Top Concept Switcher Navigation */}
      <div className="dm-lab-controls">
        <nav className="dm-concepts" aria-label="Drive design concepts">
          {DRIVE_CONCEPTS.map((concept, index) => (
            <button
              type="button"
              key={concept.id}
              aria-pressed={activeConcept.id === concept.id}
              onClick={() => selectConcept(concept.id)}
            >
              <span>0{index + 1}</span>
              {concept.name}
            </button>
          ))}
        </nav>

        <label className="dm-concept-select">
          <span>Design</span>
          <select
            aria-label="Drive design concept"
            value={activeConcept.id}
            onChange={(e) => selectConcept(e.target.value)}
          >
            {DRIVE_CONCEPTS.map((concept, index) => (
              <option key={concept.id} value={concept.id}>
                0{index + 1} · {concept.name}
              </option>
            ))}
          </select>
        </label>

        <div className="dm-lab-right-controls">
          {/* Mode Switcher: Modal Overlay vs Full Workbench */}
          <div className="dm-mode-toggle" role="group" aria-label="Presentation mode">
            <button
              type="button"
              className={`dm-mode-btn ${model.presentationMode === 'modal' ? 'is-active' : ''}`}
              onClick={() => {
                model.setPresentationMode('modal');
                model.setModalOpen(true);
              }}
            >
              Modal Dialog
            </button>
            <button
              type="button"
              className={`dm-mode-btn ${model.presentationMode === 'workbench' ? 'is-active' : ''}`}
              onClick={() => model.setPresentationMode('workbench')}
            >
              Inline Studio
            </button>
          </div>

          <button type="button" className="dm-btn--quiet" onClick={model.reset}>
            Reset preview
          </button>
        </div>
      </div>

      {/* Active Concept Explanation Banner */}
      <p className="dm-concept-note">{activeConcept.note}</p>

      {/* Interactive Sample Drive Selector Bar */}
      <div className="dm-drive-bar" role="toolbar" aria-label="Sample drive mounts">
        <span className="dm-drive-bar-label">Mount Scenarios:</span>
        {model.drives.map((d) => (
          <button
            type="button"
            key={d.id}
            className={`dm-drive-btn ${model.selectedDriveId === d.id ? 'is-active' : ''}`}
            onClick={() => {
              model.setSelectedDriveId(d.id);
              model.setModalOpen(true);
            }}
          >
            <span>{d.path}</span>
            <span className={`dm-drive-badge ${d.health}`}>{d.health}</span>
          </button>
        ))}
      </div>

      {/* Toast Notification */}
      {model.notification && (
        <div className={`dm-notification ${model.notification.type}`} role="status">
          {model.notification.type === 'success' ? '✓' : '⚠'} {model.notification.message}
        </div>
      )}

      {/* Render Active Concept either in Modal Overlay or Workbench */}
      <section
        className={`dm-stage dm-stage--${activeConcept.id}`}
        aria-label={`${activeConcept.name} workspace`}
      >
        {model.presentationMode === 'modal' ? (
          model.modalOpen ? (
            <div
              className="dm-modal-backdrop"
              onClick={() => model.setModalOpen(false)}
              role="dialog"
              aria-modal="true"
            >
              <div
                className="dm-modal-window"
                onClick={(e) => e.stopPropagation()}
                role="document"
              >
                <div className="dm-modal-bar">
                  <span>Drive Configuration — {model.selectedDrive.path}</span>
                  <button
                    type="button"
                    className="dm-modal-close"
                    onClick={() => model.setModalOpen(false)}
                    aria-label="Close configure modal"
                  >
                    ×
                  </button>
                </div>

                {activeConcept.id === 'cockpit' && <DriveCockpitConcept model={model} />}
                {activeConcept.id === 'dualpane' && <DualPaneStudioConcept model={model} />}
                {activeConcept.id === 'pipeline' && <StoragePipelineConcept model={model} />}
                {activeConcept.id === 'capacity' && <CapacityCommanderConcept model={model} />}
                {activeConcept.id === 'pro' && <DriveStudioProConcept model={model} />}
              </div>
            </div>
          ) : (
            <div style={{ textAlign: 'center', padding: '40px 20px' }}>
              <p style={{ color: 'var(--color-text-secondary, #bec8c9)', marginBottom: '12px' }}>
                Modal closed. Click button below to reopen the modal for <code>{model.selectedDrive.path}</code>.
              </p>
              <button
                type="button"
                className="dc-btn dc-btn--primary"
                onClick={() => model.setModalOpen(true)}
              >
                💾 Reopen Drive Configure Modal
              </button>
            </div>
          )
        ) : (
          <div className="dm-stage-workbench">
            {activeConcept.id === 'cockpit' && <DriveCockpitConcept model={model} />}
            {activeConcept.id === 'dualpane' && <DualPaneStudioConcept model={model} />}
            {activeConcept.id === 'pipeline' && <StoragePipelineConcept model={model} />}
            {activeConcept.id === 'capacity' && <CapacityCommanderConcept model={model} />}
            {activeConcept.id === 'pro' && <DriveStudioProConcept model={model} />}
          </div>
        )}
      </section>
    </div>
  );
}
