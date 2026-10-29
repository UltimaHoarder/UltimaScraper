import { useEffect, useId, useRef, useState, type ReactNode } from 'react';

export function StatisticsSettings({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !root.current?.contains(event.target)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setOpen(false); toggle.current?.focus(); }
    };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('keydown', escape);
    };
  }, [open]);

  return <div className="statistics-settings" ref={root}>
    <button type="button" ref={toggle} className="statistics-settings__toggle" aria-label={`${label} settings`} title={`${label} settings`} aria-expanded={open} aria-controls={id} onClick={() => setOpen((current) => !current)}>
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
        <path d="m10 2 4 0 1 3 2 1 3-1 2 4-2 2 0 2 2 2-2 4-3-1-2 1-1 3-4 0-1-3-2-1-3 1-2-4 2-2 0-2-2-2 2-4 3 1 2-1Z" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    </button>
    <div id={id} className="statistics-settings__popover" role="region" aria-label={`${label} settings`} hidden={!open}>
      <strong>Chart settings</strong>
      {children}
    </div>
  </div>;
}
