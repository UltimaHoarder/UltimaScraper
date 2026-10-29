import type { ReactNode } from 'react';

import { NumberField, WarningList } from './controls';
import {
  MOCK_SITES,
  PROXY_MODE_LABELS,
  SITE_PROFILES,
  fmt,
  formatMinutes,
  jobLabel,
  type ConceptProps,
  type MockMpsConfig,
  type MockProxyMode,
  type MockSite,
} from './mpsMockModel';

interface Recipe {
  id: string;
  title: string;
  blurb: string;
  patch: Partial<MockMpsConfig>;
}

const RECIPES: readonly Recipe[] = [
  {
    id: 'gaps',
    title: 'Fill the gaps',
    blurb: 'Discover IDs that were never stored.',
    patch: { includeMissing: true, includeInvalid: false, includeExisting: false },
  },
  {
    id: 'retry',
    title: 'Retry not-found',
    blurb: 'Give previously missing profiles another look.',
    patch: { includeMissing: false, includeInvalid: true, includeExisting: false, recheckDays: 30 },
  },
  {
    id: 'refresh',
    title: 'Refresh stale',
    blurb: 'Re-fetch stored profiles not checked recently.',
    patch: { includeMissing: false, includeInvalid: false, includeExisting: true, recheckDays: 7 },
  },
  {
    id: 'sweep',
    title: 'Full sweep',
    blurb: 'Everything eligible in the range.',
    patch: { includeMissing: true, includeInvalid: true, includeExisting: true, recheckDays: 14 },
  },
];

function Token({ children, label }: { children: ReactNode; label: string }) {
  return (
    <span className="mps-lab-token" aria-label={label}>
      {children}
    </span>
  );
}

/** Concept 05 — start from an intent, then read and edit the run as a single sentence. */
export function RecipeSentenceConcept({ model, onLaunch }: ConceptProps) {
  const { config, derived, update, setSite } = model;
  const bounds = SITE_PROFILES[config.site];
  const activeRecipe = RECIPES.find((recipe) =>
    Object.entries(recipe.patch).every(([key, value]) => config[key as keyof MockMpsConfig] === value),
  );

  return (
    <div className="mps-lab-recipe">
      <section className="mps-lab-recipe__cards" aria-label="Recipes">
        {RECIPES.map((recipe) => (
          <button
            key={recipe.id}
            type="button"
            className={activeRecipe?.id === recipe.id ? 'active' : ''}
            aria-pressed={activeRecipe?.id === recipe.id}
            onClick={() => update(recipe.patch)}
          >
            <strong>{recipe.title}</strong>
            <small>{recipe.blurb}</small>
          </button>
        ))}
      </section>

      <section className="mps-lab-sentence" aria-label="Run description">
        <p>
          Scan{' '}
          <Token label="Site">
            <select value={config.site} onChange={(event) => setSite(event.target.value as MockSite)}>
              {MOCK_SITES.map((site) => <option key={site}>{site}</option>)}
            </select>
          </Token>{' '}
          IDs from{' '}
          <Token label="First ID">
            <input type="number" value={config.startId} min={bounds.minId} style={{ width: `${String(config.startId).length + 2}ch` }} onChange={(event) => update({ startId: Number(event.target.value) })} />
          </Token>{' '}
          to{' '}
          <Token label="Last ID">
            <input type="number" value={config.endId} max={bounds.maxId} style={{ width: `${String(config.endId).length + 2}ch` }} onChange={(event) => update({ endId: Number(event.target.value) })} />
          </Token>{' '}
          for{' '}
          <Token label="Missing source">
            <button type="button" className={config.includeMissing ? 'on' : 'off'} onClick={() => update({ includeMissing: !config.includeMissing })}>new profiles</button>
          </Token>
          ,{' '}
          <Token label="Not-found source">
            <button type="button" className={config.includeInvalid ? 'on' : 'off'} onClick={() => update({ includeInvalid: !config.includeInvalid })}>past misses</button>
          </Token>{' '}
          and{' '}
          <Token label="Existing source">
            <button type="button" className={config.includeExisting ? 'on' : 'off'} onClick={() => update({ includeExisting: !config.includeExisting })}>stored profiles</button>
          </Token>
          {(config.includeInvalid || config.includeExisting) && (
            <>
              {' '}not checked in{' '}
              <Token label="Cooldown days">
                <select value={config.recheckDays} onChange={(event) => update({ recheckDays: Number(event.target.value) })}>
                  {[0, 1, 3, 7, 14, 30, 90].map((days) => <option key={days} value={days}>{days === 0 ? 'any time' : `${days} days`}</option>)}
                </select>
              </Token>
            </>
          )}
          , in batches of{' '}
          <Token label="Batch size">
            <select value={config.batchSize} onChange={(event) => update({ batchSize: Number(event.target.value) })}>
              {[...new Set([1_000, 2_500, 5_000, 10_000, 25_000, config.batchSize])].sort((a, b) => a - b).map((size) => <option key={size} value={size}>{fmt(size)}</option>)}
            </select>
          </Token>{' '}
          through{' '}
          <Token label="Routes">
            <select value={config.proxyMode} onChange={(event) => update({ proxyMode: event.target.value as MockProxyMode })}>
              {(Object.keys(PROXY_MODE_LABELS) as MockProxyMode[]).map((mode) => <option key={mode} value={mode}>{PROXY_MODE_LABELS[mode].toLowerCase()}</option>)}
            </select>
          </Token>
          .
        </p>
      </section>

      <section className="mps-lab-recipe__outcome" aria-label="What will happen">
        <ul>
          <li><strong>{fmt(derived.candidates)}</strong> profiles match across {fmt(derived.rangeCount)} ranges.</li>
          <li>The first job checks <strong>{fmt(derived.selected)}</strong>; {fmt(Math.max(0, derived.batches - 1))} more batches stay ready.</li>
          <li>Each of <strong>{derived.routeCount}</strong> routes handles about {fmt(derived.profilesPerRoute)} lookups — roughly {formatMinutes(derived.minutesPerBatch)}.</li>
        </ul>
        <WarningList warnings={derived.warnings} />
        <div className="mps-lab-recipe__launch">
          <input value={config.jobName} placeholder={jobLabel(config)} aria-label="Job name" onChange={(event) => update({ jobName: event.target.value })} />
          <button
            type="button"
            className="mps-lab-btn primary"
            disabled={derived.selected === 0}
            onClick={() => onLaunch(`${jobLabel(config)}${activeRecipe ? ` (${activeRecipe.title})` : ''}: ${fmt(derived.selected)} profiles`)}
          >
            Start
          </button>
        </div>
      </section>

      <details className="mps-lab-recipe__advanced">
        <summary>Advanced routing</summary>
        <div className="mps-lab-grid-3">
          <NumberField label="Max route hops" value={config.maxRouteHops} min={1} max={5} onChange={(maxRouteHops) => update({ maxRouteHops: Math.min(5, Math.max(1, maxRouteHops)) })} hint="Retries a profile on another route." />
          <NumberField label="Conclusive miss threshold" value={config.missThreshold} min={1} max={5} onChange={(missThreshold) => update({ missThreshold: Math.min(5, Math.max(1, missThreshold)) })} hint="Misses before marking not-found." />
          <label className="mps-lab-check">
            <input type="checkbox" checked={config.includeDirect} onChange={(event) => update({ includeDirect: event.target.checked })} /> Include direct connection
          </label>
        </div>
      </details>
    </div>
  );
}
