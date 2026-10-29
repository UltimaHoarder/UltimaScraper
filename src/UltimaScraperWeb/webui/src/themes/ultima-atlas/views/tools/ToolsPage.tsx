import { useEffect, useRef, useState } from 'react';

import { APIRequestsTool } from '../../../../features/tools/components/APIRequestsTool';
import { MPSTool } from '../../../../features/tools/components/MPSTool';
import './ToolsPage.css';

export function ToolsPage() {
  const [activeTab, setActiveTab] = useState<'mps' | 'api'>('mps');
  const [toolSearch, setToolSearch] = useState('');
  const toolsNavRef = useRef<HTMLElement>(null);
  const activeToolRef = useRef<HTMLButtonElement>(null);
  const tools = [
    { id: 'mps', label: 'Mass Profile Scraper', icon: '◎' },
    { id: 'api', label: 'API Requests', icon: '{ }' },
  ] as const;
  const visibleTools = tools.filter((tool) =>
    `${tool.label} ${tool.id}`.toLowerCase().includes(toolSearch.trim().toLowerCase())
  );

  useEffect(() => {
    const revealActiveTool = () => {
      const nav = toolsNavRef.current;
      const activeTool = activeToolRef.current;
      if (!nav || !activeTool) return;

      const navRect = nav.getBoundingClientRect();
      const toolRect = activeTool.getBoundingClientRect();
      const toolLeft = toolRect.left - navRect.left;
      const toolRight = toolRect.right - navRect.left;
      if (toolLeft < 0 || toolRight > nav.clientWidth) {
        const centeredOffset = toolLeft - (nav.clientWidth - toolRect.width) / 2;
        nav.scrollTo({ left: nav.scrollLeft + centeredOffset, behavior: 'smooth' });
      }
    };
    revealActiveTool();
    window.addEventListener('resize', revealActiveTool);
    return () => window.removeEventListener('resize', revealActiveTool);
  }, [activeTab, toolSearch]);

  return (
    <div className="tools-page">
      <section className="tools-workspace-stage" aria-label="Tools workspace">
        <header className="tools-workspace-header">
          <div className="tools-workspace-title">
            <span className="tools-workspace-symbol" aria-hidden="true">⛭</span>
            <div className="tools-workspace-copy">
              <span className="tools-workspace-kicker">Platform</span>
              <h1 className="tools-workspace-heading">Tools</h1>
              <p className="tools-workspace-subtitle">Platform utilities</p>
            </div>
          </div>
          <div className="tools-workspace-meta">
            <span className="tools-active-tool">
              <span className="ultimur-topbar__dot" />
              <span className="tools-active-label">
                {activeTab === 'mps' ? 'MPS' : tools.find((tool) => tool.id === activeTab)?.label}
              </span>
            </span>
          </div>
        </header>

        <div className="tools-search-row">
          <label className="tools-search" title="Search available tools">
            <span className="tools-search-icon" aria-hidden="true">🔍</span>
            <input
              type="text"
              aria-label="Search tools"
              aria-controls="tools-selector-list"
              placeholder="Search tools"
              value={toolSearch}
              onChange={(event) => setToolSearch(event.target.value)}
            />
            {toolSearch ? (
              <button
                type="button"
                className="tools-search-clear"
                aria-label="Clear tool search"
                onClick={() => setToolSearch('')}
              >
                ×
              </button>
            ) : null}
          </label>
        </div>

        <nav ref={toolsNavRef} id="tools-selector-list" className="tools-selector" aria-label="Tools" tabIndex={0}>
          {visibleTools.length > 0 ? <div className="tools-tabs">
            {visibleTools.map((tool) => (
              <button
                key={tool.id}
                type="button"
                ref={activeTab === tool.id ? activeToolRef : undefined}
                className={`tools-tab ${activeTab === tool.id ? 'active' : ''}`}
                aria-current={activeTab === tool.id ? 'page' : undefined}
                onClick={() => setActiveTab(tool.id)}
              >
                <span className="tools-tab-icon" aria-hidden="true">{tool.icon}</span>
                <span className="tools-tab-label">{tool.label}</span>
              </button>
            ))}
          </div> : <p className="tools-no-results" role="status">No tools match “{toolSearch.trim()}”.</p>}
        </nav>
      </section>

      <main className="tools-content" id="tools-content" tabIndex={-1}>
        {activeTab === 'mps' && <MPSTool />}
        {activeTab === 'api' && <APIRequestsTool />}
      </main>
    </div>
  );
}
