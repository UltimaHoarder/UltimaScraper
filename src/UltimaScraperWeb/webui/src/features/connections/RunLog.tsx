import { useEffect, useRef } from 'react';

import type { InstallEvent } from '../../api/webui';

export function RunLog({ events }: { events: InstallEvent[] }) {
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    listRef.current?.lastElementChild?.scrollIntoView?.({ block: 'nearest' });
  }, [events]);

  return (
    <ol className="deploy-log" ref={listRef} aria-live="polite">
      {events.map((entry) => (
        <li key={entry.seq} className={`is-${entry.kind}`}>
          {entry.message}
        </li>
      ))}
    </ol>
  );
}
