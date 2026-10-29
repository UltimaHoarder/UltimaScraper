import { useEffect, useState } from 'react';

import { getInstall, type InstallEvent, type InstallStatus } from '../../../api/webui';

interface Run {
  id: string | null;
  status: InstallStatus | null;
  events: InstallEvent[];
}

const EMPTY: Run = { id: null, status: null, events: [] };

/**
 * Follows an install or an operation until it finishes. Events carry on from
 * the last one seen, so a slow poll or a reconnect loses nothing.
 */
export function useInstallRun(runId: string | null): { status: InstallStatus | null; events: InstallEvent[] } {
  const [run, setRun] = useState<Run>(EMPTY);

  useEffect(() => {
    if (!runId) return;
    let after = 0;
    let stopped = false;
    const poll = async () => {
      while (!stopped) {
        try {
          const current = await getInstall(runId, after);
          if (current.events.length) after = current.events[current.events.length - 1].seq;
          setRun((previous) => ({
            id: runId,
            status: current,
            // A new run starts from no events.
            events: [...(previous.id === runId ? previous.events : []), ...current.events],
          }));
          if (current.state !== 'running') return;
        } catch {
          // Keep trying; the run carries on regardless.
        }
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
    };
    void poll();
    return () => {
      stopped = true;
    };
  }, [runId]);

  return run.id === runId ? run : EMPTY;
}
