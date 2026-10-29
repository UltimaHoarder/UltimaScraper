import { useState } from 'react';
export function StatisticsDateRange({ label, initialStart, onApply }: { label: string; initialStart?: string; onApply: (dates: { start: string; end: string }) => void }) {
  const [today] = useState(() => new Date().toISOString().slice(0, 10));
  const [start, setStart] = useState(initialStart ?? '');
  const [end, setEnd] = useState(today);
  const invalid = !start || !end || start > end || start > today;
  return <form className="statistics-custom-range" onSubmit={(e) => { e.preventDefault(); if (!invalid) onApply({ start, end }); }}>
    <label><span>{label} from</span><input aria-label={`${label} from`} type="date" min="1900-01-01" max={end} required value={start} onChange={(e) => setStart(e.target.value)} /></label>
    <label><span>{label} through</span><input aria-label={`${label} through`} type="date" min={start} max={today} required value={end} onChange={(e) => setEnd(e.target.value)} /></label>
    <button type="submit" disabled={invalid}>Apply dates</button>
    <small>UTC · End date included</small>
  </form>;
}
