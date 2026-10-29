import { createContext, useContext, useId, useState, type ReactNode } from 'react';
import { StatisticsChartSettingsContext } from './statisticsChartSettings';

const RowContext = createContext<{ expanded: string | null; toggle: (id: string) => void } | null>(null);

export function StatisticsVisualizationRow({ children }: { children: ReactNode }) {
  const [expanded, setExpanded] = useState<string | null>(null);
  return <RowContext.Provider value={{ expanded, toggle: (id) => setExpanded((current) => current === id ? null : id) }}>
    <div className={`statistics-visualization-row${expanded ? ' has-expanded' : ''}`}>{children}</div>
  </RowContext.Provider>;
}

export function StatisticsPanel({ label, className = '', settings, children }: { label: string; className?: string; settings?: ReactNode; children: ReactNode }) {
  const id = useId();
  const row = useContext(RowContext);
  const [standaloneExpanded, setStandaloneExpanded] = useState(false);
  const expanded = row ? row.expanded === id : standaloneExpanded;

  return <StatisticsChartSettingsContext.Provider value={{ label, settings }}><section className={`statistics-panel statistics-visualization ${className}${expanded ? ' is-expanded' : ''}`} aria-label={label} hidden={!!row?.expanded && !expanded}>
    <div className="statistics-panel__actions">
    <button
      type="button"
      className="statistics-expand"
      aria-label={`${expanded ? 'Collapse' : 'Expand'} ${label}`}
      aria-expanded={expanded}
      onClick={() => row ? row.toggle(id) : setStandaloneExpanded((current) => !current)}
    >
      <span aria-hidden="true">{expanded ? '↙' : '↗'}</span> {expanded ? 'Collapse' : 'Expand'}
    </button>
    </div>
    {children}
  </section></StatisticsChartSettingsContext.Provider>;
}
