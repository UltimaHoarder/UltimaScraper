import { useCallback, useEffect, useState, type ComponentType } from 'react';

import { BatchRunwayConcept } from './BatchRunwayConcept';
import { CommandDeckConcept } from './CommandDeckConcept';
import { GuidedFlowConcept } from './GuidedFlowConcept';
import { IdSpaceMapConcept } from './IdSpaceMapConcept';
import { RecipeSentenceConcept } from './RecipeSentenceConcept';
import { useMockMpsModel, type ConceptProps } from './mpsMockModel';
import './MpsRedesigns.css';

interface Concept {
  id: string;
  name: string;
  pitch: string;
  bestFor: string;
  tradeoff: string;
  Component: ComponentType<ConceptProps>;
}

const CONCEPTS: readonly Concept[] = [
  {
    id: 'guided',
    name: 'Guided Flow',
    pitch: 'One decision per step with a running receipt.',
    bestFor: 'New operators and infrequent runs.',
    tradeoff: 'Slower for experts who already know the settings.',
    Component: GuidedFlowConcept,
  },
  {
    id: 'deck',
    name: 'Command Deck',
    pitch: 'Every input, the equivalent command, and preflight checks on one screen.',
    bestFor: 'Power users running MPS daily.',
    tradeoff: 'Dense; little explanation of what each field means.',
    Component: CommandDeckConcept,
  },
  {
    id: 'map',
    name: 'ID-Space Map',
    pitch: 'Brush the candidate density map to choose where to scan.',
    bestFor: 'Finding dense pockets and avoiding empty ranges.',
    tradeoff: 'Needs a cheap density endpoint to feel live.',
    Component: IdSpaceMapConcept,
  },
  {
    id: 'runway',
    name: 'Batch Runway',
    pitch: 'Plan the whole run as batches and see per-route load first.',
    bestFor: 'Large candidate sets split across many jobs.',
    tradeoff: 'Assumes scope and sources are already decided.',
    Component: BatchRunwayConcept,
  },
  {
    id: 'recipe',
    name: 'Recipe & Sentence',
    pitch: 'Start from an intent, then edit the run as a sentence.',
    bestFor: 'Quick, readable runs; explaining a run to someone else.',
    tradeoff: 'Advanced routing is tucked away.',
    Component: RecipeSentenceConcept,
  },
];

export function MpsRedesignsMock() {
  const model = useMockMpsModel();
  const [activeId, setActiveId] = useState(CONCEPTS[0].id);
  const [notice, setNotice] = useState<string | null>(null);
  const active = CONCEPTS.find((concept) => concept.id === activeId) ?? CONCEPTS[0];

  const handleLaunch = useCallback((summary: string) => setNotice(summary), []);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 6_000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  return (
    <div className="mps-lab">
      <nav className="mps-lab-concepts" aria-label="Redesign concepts">
        {CONCEPTS.map((concept, index) => (
          <button
            key={concept.id}
            type="button"
            className={concept.id === active.id ? 'active' : ''}
            aria-current={concept.id === active.id ? 'page' : undefined}
            onClick={() => setActiveId(concept.id)}
          >
            <span className="num">{String(index + 1).padStart(2, '0')}</span>
            <strong>{concept.name}</strong>
            <small>{concept.pitch}</small>
          </button>
        ))}
      </nav>

      <div className="mps-lab-brief">
        <div><span>Best for</span>{active.bestFor}</div>
        <div><span>Trade-off</span>{active.tradeoff}</div>
        <button type="button" className="mps-lab-btn ghost" onClick={model.reset}>Reset mock data</button>
      </div>

      {notice && (
        <div className="mps-lab-notice" role="status">
          <strong>Mock launch</strong>
          <span>{notice}. Nothing was queued.</span>
          <button type="button" aria-label="Dismiss" onClick={() => setNotice(null)}>×</button>
        </div>
      )}

      <section className="mps-lab-stage" aria-label={`${active.name} concept`}>
        <active.Component model={model} onLaunch={handleLaunch} />
      </section>
    </div>
  );
}
