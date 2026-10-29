import { useEffect, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useAppBootstrap } from '../../../app/bootstrap/AppBootstrapProvider';
import { useTheme } from '../../../app/theme/useTheme';
import type { SidebarShellProps, ThemeId } from '../../../app/theme/types';
import { getNavigationSections, isNavItemActive } from '../../../components/layout/navigation';
import { NavIcon } from '../../../components/layout/NavIcon';
import { AtlasMark } from './AtlasMark';
import { PluginNavigation } from '../../../features/plugins/components/PluginNavigation';
import { FailoverNotice } from '../../../features/connections/FailoverNotice';
import { useDevMode } from '../../../features/settings/hooks/useWebUIPreferences';

const sectionNames: Record<string, string> = {
  Monitor: '01 // Telemetry', Jobs: '02 // Operations', Content: '03 // Data vault',
  People: '04 // Identities', Platform: '05 // Infrastructure', Settings: '06 // Configuration',
};

export function Sidebar({ isOpen, onClose, statusText }: SidebarShellProps) {
  const location = useLocation();
  const devMode = useDevMode();
  return (
    <>
      <button className={`atlas-overlay ${isOpen ? 'is-open' : ''}`} onClick={onClose} aria-label="Close navigation" tabIndex={isOpen ? 0 : -1} />
      <aside id="atlas-navigation" className={`atlas-sidebar ${isOpen ? 'is-open' : ''}`}>
        <NavLink className="atlas-brand" to="/" onClick={onClose} aria-label="UltimaScraper dashboard">
          <AtlasMark />
          <span><strong>ULTIMA</strong><small>DATA ACQUISITION SYSTEMS</small></span>
        </NavLink>
        <nav aria-label="Primary navigation">
          {getNavigationSections(devMode).map((section) => (
            <section key={section.title}>
              <h2>{sectionNames[section.title] ?? section.title}</h2>
              {section.items.map((item) => (
                <NavLink key={item.path} to={item.path} end={item.exact ?? false} onClick={onClose}
                  className={({ isActive }) => `atlas-nav-link ${isNavItemActive(item, location.pathname, location.search, isActive) ? 'is-active' : ''}`}>
                  <NavIcon name={item.icon} /><span>{item.label}</span>
                </NavLink>
              ))}
            </section>
          ))}
          {devMode && <PluginNavigation onNavigate={onClose} />}
        </nav>
        <footer><span>US-CT // ULTIMA ATLAS</span><small>{statusText}</small></footer>
      </aside>
    </>
  );
}

export function AppShell() {
  const [open, setOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const sidebarRef = useRef<HTMLDivElement>(null);
  const location = useLocation();
  const { statusText } = useAppBootstrap();
  const { theme, themes, setTheme } = useTheme();
  const close = () => { setOpen(false); toggleRef.current?.focus(); };

  useEffect(() => {
    const frame = requestAnimationFrame(() => setOpen(false));
    return () => cancelAnimationFrame(frame);
  }, [location.pathname, location.search]);

  useEffect(() => {
    const desktop = window.matchMedia('(min-width: 1024px)');
    const resize = () => { if (desktop.matches) setOpen(false); };
    desktop.addEventListener('change', resize);
    return () => desktop.removeEventListener('change', resize);
  }, []);

  useEffect(() => {
    if (!open) return;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    sidebarRef.current?.querySelector<HTMLAnchorElement>('a')?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setOpen(false); toggleRef.current?.focus(); }
      if (event.key !== 'Tab') return;
      const controls = Array.from(sidebarRef.current?.querySelectorAll<HTMLElement>('a, button') ?? []).filter((element) => element.offsetParent !== null);
      const first = controls[0];
      const last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    document.addEventListener('keydown', keydown);
    return () => { document.body.style.overflow = oldOverflow; document.removeEventListener('keydown', keydown); };
  }, [open]);

  return (
    <div className="atlas-layout">
      <a href="#atlas-main" className="atlas-skip">Skip to content</a>
      <div ref={sidebarRef}><Sidebar isOpen={open} onClose={close} statusText={statusText} /></div>
      <div className="atlas-workspace">
        <header className="atlas-shell-header">
          <button ref={toggleRef} className="atlas-menu" type="button" aria-label={open ? 'Close menu' : 'Open menu'} aria-expanded={open} aria-controls="atlas-navigation" onClick={() => setOpen(!open)}>
            <NavIcon name="logs" />
          </button>
          <span>ULTIMASCRAPER <small>/ DISTRIBUTED ACQUISITION NETWORK</small></span>
          <FailoverNotice />
          {/* Matches the Settings appearance section: a single theme offers no choice. */}
          {themes.length > 1 && (
            <label className="atlas-theme"><span className="sr-only">Active theme</span>
              <select aria-label="Active theme" value={theme.id} onChange={(event) => setTheme(event.target.value as ThemeId)}>
                {themes.map((entry) => <option key={entry.id} value={entry.id}>{entry.label}</option>)}
              </select>
            </label>
          )}
        </header>
        <main id="atlas-main" className="atlas-main" tabIndex={-1} inert={open}><Outlet /></main>
        <footer className="atlas-shell-footer"><span>ULTIMA // CONTROL</span><span>ACQUIRE. PROCESS. PRESERVE.</span></footer>
      </div>
    </div>
  );
}
