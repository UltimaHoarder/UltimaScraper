import { useSearchParams } from 'react-router-dom';
import { useJobCreatorMockModel } from './jobCreatorMockModel';
import { DualModeStudioConcept } from './DualModeStudioConcept';
import { PipelineBlueprintConcept } from './PipelineBlueprintConcept';
import { RapidCommandConcept } from './RapidCommandConcept';
import { RecipeRunwayConcept } from './RecipeRunwayConcept';
import { MatrixDispatcherConcept } from './MatrixDispatcherConcept';
import './JobCreatorRedesignsMock.css';

export const JOB_CREATOR_CONCEPTS = [
  {
    id: 'studio',
    name: 'Dual-Mode Studio & Template Lab',
    note: 'Unified 3-tab creation studio: Custom Task Builder with inline Save-as-Template, Template Runner with performer autocomplete & auth qualification, and dedicated Template Authoring Lab.',
  },
  {
    id: 'blueprint',
    name: 'Pipeline Blueprint Architect',
    note: 'Visual node-based DAG workflow chain revealing task dependencies, data flow, bypassable stages, and one-click "Save Pipeline as Named Template".',
  },
  {
    id: 'terminal',
    name: 'Rapid Command Terminal',
    note: 'High-velocity operator deck with 1-click task injection, multi-line handle paste, "Save Queue as Template" modal, and live real-time API payload debugger.',
  },
  {
    id: 'recipe',
    name: 'Recipe & Template Runway',
    note: 'Template-first modular workbench featuring curated workload archetypes, dedicated interactive Template Creator with parameter schema builder, and performer qualification.',
  },
  {
    id: 'matrix',
    name: 'Matrix Batch Dispatcher',
    note: 'Spreadsheet-style multi-creator workbench allowing granular per-creator policies, sticky bulk multi-row operations, and 1-click "Save Grid as Named Template".',
  },
] as const;

export type JobCreatorConceptId = typeof JOB_CREATOR_CONCEPTS[number]['id'];

export function JobCreatorRedesignsMock() {
  const model = useJobCreatorMockModel();
  const [params, setParams] = useSearchParams();

  const requestedConcept = params.get('concept') as JobCreatorConceptId | null;
  const activeConcept =
    JOB_CREATOR_CONCEPTS.find((c) => c.id === requestedConcept) ?? JOB_CREATOR_CONCEPTS[0];

  const selectConcept = (id: string) => {
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.set('category', 'create-job');
      next.set('concept', id);
      return next;
    });
    window.scrollTo({ top: 0, behavior: 'instant' });
  };

  return (
    <div className="jcm-lab" data-testid="job-creator-redesigns-mock">
      {/* Top Concept Switcher Navigation */}
      <div className="jcm-lab-controls">
        <nav className="jcm-concepts" aria-label="Job creator design concepts">
          {JOB_CREATOR_CONCEPTS.map((concept, index) => (
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

        <label className="jcm-concept-select">
          <span>Design</span>
          <select
            aria-label="Job creator design concept"
            value={activeConcept.id}
            onChange={(e) => selectConcept(e.target.value)}
          >
            {JOB_CREATOR_CONCEPTS.map((concept, index) => (
              <option key={concept.id} value={concept.id}>
                0{index + 1} · {concept.name}
              </option>
            ))}
          </select>
        </label>

        <div className="jcm-lab-right-controls">
          <button type="button" className="jcm-quiet-btn" onClick={model.resetAll}>
            Reset preview
          </button>
        </div>
      </div>

      {/* Concept Pitch Note */}
      <p className="jcm-concept-note">{activeConcept.note}</p>

      {/* Global Interactive Notification Toast */}
      {model.notification && (
        <div className={`jcm-notification is-${model.notification.type}`} role="status">
          <span>⚡ {model.notification.message}</span>
          <small>Interactive preview feedback</small>
        </div>
      )}

      {/* Stage Workspace Header */}
      <header className="jcm-workspace-header">
        <div>
          <span className="jcm-eyebrow">US-CT // WORKLOAD COMPOSER</span>
          <h2>{activeConcept.name}</h2>
        </div>
        <div className="jcm-workspace-meta">
          <span className="jcm-pill is-running">READY FOR DISPATCH</span>
          <code>NODE: backend_local</code>
        </div>
      </header>

      {/* Render Active Concept */}
      <div className="jcm-stage">
        {activeConcept.id === 'studio' && <DualModeStudioConcept model={model} />}
        {activeConcept.id === 'blueprint' && <PipelineBlueprintConcept model={model} />}
        {activeConcept.id === 'terminal' && <RapidCommandConcept model={model} />}
        {activeConcept.id === 'recipe' && <RecipeRunwayConcept model={model} />}
        {activeConcept.id === 'matrix' && <MatrixDispatcherConcept model={model} />}
      </div>
    </div>
  );
}
