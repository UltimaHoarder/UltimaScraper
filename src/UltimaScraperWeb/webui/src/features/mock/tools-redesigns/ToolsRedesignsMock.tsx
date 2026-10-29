import { useState } from 'react';
import './ToolsRedesignsMock.css';

type ToolId = 'restore' | 'mps' | 'directory' | 'api' | 'mentions';
type LayoutId = 'launchpad' | 'workbench' | 'guided' | 'command' | 'activity';

const TOOLS: Array<{ id: ToolId; name: string; eyebrow: string; description: string; icon: string }> = [
  { id: 'restore', name: 'Server Restore', eyebrow: 'Recovery', description: 'Review and restore matching performer files into a server archive.', icon: '↺' },
  { id: 'mps', name: 'Mass Profile Scraper', eyebrow: 'Discovery', description: 'Analyze profile ID ranges, preview candidates, then create a bounded job.', icon: '◎' },
  { id: 'directory', name: 'Directory Search', eyebrow: 'Lookup', description: 'Find configured download folders by username or platform ID.', icon: '⌕' },
  { id: 'api', name: 'API Requests', eyebrow: 'Developer', description: 'Choose an authenticated site session and inspect an API method response.', icon: '{ }' },
  { id: 'mentions', name: 'Content Mentions', eyebrow: 'Archive', description: 'Preview or apply a backfill of explicit handles and legacy linked users.', icon: '@' },
];

const LAYOUTS: Array<{ id: LayoutId; name: string; pitch: string; bestFor: string; tradeoff: string }> = [
  { id: 'launchpad', name: 'Tool Launchpad', pitch: 'A calm catalog with clear starting points.', bestFor: 'Occasional use and discovery.', tradeoff: 'The active workspace sits below the catalog.' },
  { id: 'workbench', name: 'Operator Workbench', pitch: 'Keep navigation and the current task side by side.', bestFor: 'Switching between tools during a session.', tradeoff: 'Uses more horizontal space.' },
  { id: 'guided', name: 'Guided Desk', pitch: 'Orient each task with a short purpose and next step.', bestFor: 'Infrequent or higher impact workflows.', tradeoff: 'Adds context before the controls.' },
  { id: 'command', name: 'Command Shelf', pitch: 'Filter the tool list and open a focused workspace.', bestFor: 'Fast keyboard and search driven access.', tradeoff: 'The catalog is less visual.' },
  { id: 'activity', name: 'Recent Work', pitch: 'Pair the tool catalog with resumable local sessions.', bestFor: 'Returning to work already in progress.', tradeoff: 'Recent items need careful status labeling.' },
];

function ToolGlyph({ tool }: { tool: typeof TOOLS[number] }) {
  return <span className="tools-mock-glyph" aria-hidden="true">{tool.icon}</span>;
}

function ToolList({ selected, onSelect, compact = false }: { selected: ToolId; onSelect: (id: ToolId) => void; compact?: boolean }) {
  return <div className={`tools-mock-list${compact ? ' tools-mock-list--compact' : ''}`}>
    {TOOLS.map((tool) => <button type="button" key={tool.id} className={selected === tool.id ? 'is-selected' : ''} aria-pressed={selected === tool.id} onClick={() => onSelect(tool.id)}>
      <ToolGlyph tool={tool} /><span className="tools-mock-list-copy"><strong>{tool.name}</strong>{!compact && <small>{tool.description}</small>}</span><span className="tools-mock-arrow" aria-hidden="true">›</span>
    </button>)}
  </div>;
}

function SampleWorkspace({ toolId, onAction }: { toolId: ToolId; onAction: () => void }) {
  const tool = TOOLS.find((item) => item.id === toolId)!;
  return <section className="tools-mock-workspace" aria-label={`${tool.name} preview`}>
    <header className="tools-mock-workspace-head"><div><span className="tools-mock-overline">{tool.eyebrow} · sample workspace</span><h3><ToolGlyph tool={tool} />{tool.name}</h3><p>{tool.description}</p></div><span className="tools-mock-sample-tag">Preview only</span></header>
    {toolId === 'mps' && <div className="tools-mock-fields"><label>Site<select defaultValue="OnlyFans"><option>OnlyFans</option><option>Fansly</option></select></label><label>Start profile ID<input defaultValue="100000" /></label><label>End profile ID<input defaultValue="120000" /></label><label>Maximum profiles<input defaultValue="500" /></label><div className="tools-mock-inline-note">Analyze the candidate set before creating a job.</div></div>}
    {toolId === 'directory' && <div className="tools-mock-fields"><label>Identifier<input defaultValue="@samplecreator" /></label><label>Site<select defaultValue="OnlyFans"><option>OnlyFans</option><option>Fansly</option></select></label><div className="tools-mock-result"><span>Example match</span><code>/downloads/onlyfans/samplecreator</code></div></div>}
    {toolId === 'api' && <div className="tools-mock-fields"><label>Site<select defaultValue="OnlyFans"><option>OnlyFans</option><option>Fansly</option></select></label><label>Auth<select defaultValue="Sample session"><option>Sample session</option></select></label><label className="tools-mock-wide">Method<select defaultValue="user.get"><option>user.get</option><option>posts.list</option></select></label><div className="tools-mock-code">{'{ "user_id": 123456 }'}</div></div>}
    {toolId === 'mentions' && <div className="tools-mock-fields"><label>Archive site<select defaultValue="OnlyFans"><option>OnlyFans</option><option>Fansly</option><option>LoyalFans</option></select></label><label>Batch size<input defaultValue="500000" /></label><label>Parallel workers<input defaultValue="32" /></label><div className="tools-mock-inline-note">Start with a read-only preview; applying is a separate step.</div></div>}
    {toolId === 'restore' && <div className="tools-mock-restore"><ol><li className="is-current">Discover archive</li><li>Select performers</li><li>Review actions</li><li>Preflight</li><li>Restore &amp; verify</li></ol><div><strong>Review before restore</strong><p>Select the archive and inspect the proposed file actions before applying them.</p><span className="tools-mock-path">/server/archive/example</span></div></div>}
    <footer className="tools-mock-workspace-foot"><button type="button" className="tools-mock-primary" onClick={onAction}>{toolId === 'mps' ? 'Analyze profiles' : toolId === 'directory' ? 'Search directories' : toolId === 'api' ? 'Execute request' : toolId === 'mentions' ? 'Preview backfill' : 'Start discovery'}</button><span>Clicking shows a local preview message only.</span></footer>
  </section>;
}

export function ToolsRedesignsMock() {
  const [layoutId, setLayoutId] = useState<LayoutId>('launchpad');
  const [toolId, setToolId] = useState<ToolId>('mps');
  const [notice, setNotice] = useState('Sample data · interactions stay in this preview');
  const layout = LAYOUTS.find((item) => item.id === layoutId)!;
  const selectTool = (id: ToolId) => { setToolId(id); setNotice(`Showing the ${TOOLS.find((item) => item.id === id)!.name} sample`); };
  const action = () => setNotice(`${TOOLS.find((item) => item.id === toolId)!.name} action previewed · nothing was sent`);
  return <div className={`tools-mock-lab tools-mock-lab--${layoutId}`}>
    <nav className="tools-mock-concepts" aria-label="Tools page concepts">{LAYOUTS.map((item, index) => <button key={item.id} type="button" className={item.id === layoutId ? 'is-active' : ''} aria-pressed={item.id === layoutId} onClick={() => setLayoutId(item.id)}><span>0{index + 1}</span><strong>{item.name}</strong><small>{item.pitch}</small></button>)}</nav>
    <div className="tools-mock-brief"><div><span>Best for</span>{layout.bestFor}</div><div><span>Trade-off</span>{layout.tradeoff}</div><button type="button" onClick={() => { setToolId('mps'); setNotice('Sample data · interactions stay in this preview'); }}>Reset preview</button></div>
    <div className="tools-mock-stage">
      {layoutId === 'launchpad' && <><header className="tools-mock-page-title"><div><span>Platform workspace</span><h2>Choose a tool</h2><p>Focused utilities for discovery, recovery, lookup, and archive maintenance.</p></div><label>Find a tool<input placeholder="Search tools…" /></label></header><ToolList selected={toolId} onSelect={selectTool} /><SampleWorkspace toolId={toolId} onAction={action} /></>}
      {layoutId === 'workbench' && <><aside className="tools-mock-rail"><div className="tools-mock-rail-title">TOOLS <small>05</small></div><ToolList selected={toolId} onSelect={selectTool} compact /></aside><div className="tools-mock-main"><header className="tools-mock-page-title"><div><span>Workspace / {TOOLS.find((item) => item.id === toolId)!.name}</span><h2>Work area</h2><p>Tool selection stays available while the current task is open.</p></div></header><SampleWorkspace toolId={toolId} onAction={action} /></div></>}
      {layoutId === 'guided' && <><header className="tools-mock-page-title"><div><span>Guided tools</span><h2>What are you here to do?</h2><p>Start with the outcome; the next step stays visible as you work.</p></div></header><div className="tools-mock-guided"><ToolList selected={toolId} onSelect={selectTool} /><div className="tools-mock-guide-card"><span>YOUR WORKFLOW</span><strong>{TOOLS.find((item) => item.id === toolId)!.name}</strong><p>{TOOLS.find((item) => item.id === toolId)!.description}</p><div className="tools-mock-guide-step"><b>01</b><span>{toolId === 'restore' ? 'Discover and review' : toolId === 'mentions' ? 'Preview the backfill' : toolId === 'directory' ? 'Enter an identifier' : toolId === 'api' ? 'Select a session and method' : 'Define the candidate range'}</span></div><button type="button" className="tools-mock-primary" onClick={action}>Continue to workspace <span aria-hidden="true">→</span></button></div></div><SampleWorkspace toolId={toolId} onAction={action} /></>}
      {layoutId === 'command' && <><header className="tools-mock-page-title"><div><span>Quick access</span><h2>Tool directory</h2><p>Search by tool name or the task you want to complete.</p></div></header><div className="tools-mock-command"><label className="tools-mock-search">⌕<input placeholder="Search tools or actions…" /><kbd>⌘ K</kbd></label><div className="tools-mock-command-columns"><div><span className="tools-mock-overline">ALL TOOLS</span><ToolList selected={toolId} onSelect={selectTool} compact /></div><SampleWorkspace toolId={toolId} onAction={action} /></div></div></>}
      {layoutId === 'activity' && <><header className="tools-mock-page-title"><div><span>Workspace</span><h2>Recent work</h2><p>Resume a saved review or open a tool for a new task.</p></div><button type="button" className="tools-mock-secondary" onClick={() => setNotice('New task preview · no session was created')}>＋ New task</button></header><div className="tools-mock-activity"><section className="tools-mock-recent"><span className="tools-mock-overline">SAMPLE SESSIONS</span><button type="button" onClick={() => { setToolId('restore'); setNotice('Example restore review selected'); }}><b>Server Restore</b><span>Review · performer selection</span><small>Example session</small></button><button type="button" onClick={() => { setToolId('mentions'); setNotice('Example mention preview selected'); }}><b>Content Mentions</b><span>Preview · OnlyFans archive</span><small>Example session</small></button><div className="tools-mock-session-note">Examples only · no live session state</div></section><section className="tools-mock-available"><span className="tools-mock-overline">OPEN A TOOL</span><ToolList selected={toolId} onSelect={selectTool} compact /></section></div><SampleWorkspace toolId={toolId} onAction={action} /></>}
    </div>
    <footer className="tools-mock-notice" role="status"><span>{notice}</span><span>Illustrative layout · sample data</span></footer>
  </div>;
}
