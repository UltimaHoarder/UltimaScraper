import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useDevMode } from '../hooks/useWebUIPreferences';
import './DevModeGate.css';

/** Shows its page only while Developer mode is on. */
export function DevModeGate({ children }: { children: ReactNode }) {
  const devMode = useDevMode();
  if (devMode) return <>{children}</>;
  return (
    <section className="dev-mode-gate" aria-label="Developer mode is off">
      <h1>Developer mode is off</h1>
      <p>Plugins and the design lab only run while Developer mode is on.</p>
      <Link to="/settings?tab=developer">Open Developer settings</Link>
    </section>
  );
}
