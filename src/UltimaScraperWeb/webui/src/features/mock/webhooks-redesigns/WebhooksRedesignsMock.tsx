import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useWebhooksMockModel, type WebhooksMockModel } from './webhooksMockModel';
import { Icon, Tag, Overview, MessageWorkspace, RouteWorkspace, WatchWorkspace } from '../../webhooks/components/WebhooksDesignWorkspace';
import '../../webhooks/components/WebhooksDesignWorkspace.css';

type Area = 'overview' | 'messages' | 'config' | 'watch';
const CONCEPTS = [
  { id: 'signal', name: 'Signal Desk', note: 'A focused overview with quick paths to messages, hooks, and watched users.', area: 'overview' },
  { id: 'journal', name: 'Event Journal', note: 'Read events in sequence and open their payloads in context.', area: 'messages' },
  { id: 'register', name: 'Route Register', note: 'Compare hook configurations and inspect a destination without leaving the table.', area: 'config' },
  { id: 'studio', name: 'Watch Studio', note: 'Find and manage watched users, with a clear last-download record.', area: 'watch' },
  { id: 'console', name: 'Split Console', note: 'Keep the event list, selected payload, and site hooks within reach.', area: 'messages' },
] as const;
type Concept = typeof CONCEPTS[number];

function Workspace({ model, concept }: { model: WebhooksMockModel; concept: Concept }) {
  const [area, setArea] = useState<Area>(concept.area);
  return <section className={`wh-stage wh-stage--${concept.id}`} aria-label={`${concept.name} design`}><header className="wh-workspace-header"><div className="wh-workspace-title"><span className="wh-workspace-symbol"><Icon name={concept.id === 'studio' ? 'people' : concept.id === 'register' ? 'route' : 'signal'} /></span><div><h2>{concept.id === 'studio' ? 'Watch list' : 'Webhooks'}</h2><p>{concept.id === 'studio' ? 'Keep the creators you follow within reach.' : 'Your hooks, messages, and watched users.'}</p></div></div><Tag tone={model.connected ? 'accent' : 'warning'}><span className="wh-dot" />{model.connected ? 'Stream connected' : 'Stream offline'}</Tag></header><nav className="wh-workspace-nav" aria-label="Webhook workspace">{([{ id: 'overview', label: 'Overview', icon: 'signal' }, { id: 'messages', label: 'Messages', icon: 'message' }, { id: 'config', label: 'Configuration', icon: 'route' }, { id: 'watch', label: 'Watch list', icon: 'people' }] as const).map((item) => <button type="button" key={item.id} aria-pressed={area === item.id} onClick={() => setArea(item.id)}><Icon name={item.icon} />{item.label}{item.id === 'watch' && <small>{model.users.length}</small>}</button>)}</nav>{!model.connected && <div className="wh-banner"><strong>Event stream offline</strong><span>Cached sample messages remain available.</span></div>}{model.paused && <div className="wh-banner"><strong>Watch processing paused</strong><span>Incoming messages remain available.</span></div>}<div className="wh-workspace-body">{area === 'overview' && <Overview model={model} navigate={setArea} />}{area === 'messages' && <MessageWorkspace model={model} concept={concept} />}{area === 'config' && <RouteWorkspace model={model} />}{area === 'watch' && <WatchWorkspace model={model} studio={concept.id === 'studio'} />}</div></section>;
}

export function WebhooksRedesignsMock() {
  const model = useWebhooksMockModel();
  const [params, setParams] = useSearchParams();
  const active = CONCEPTS.find((concept) => concept.id === params.get('concept')) ?? CONCEPTS[0];
  function selectConcept(id: string) {
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.set('category', 'webhooks');
      next.set('concept', id);
      return next;
    });
    window.scrollTo({ top: 0, behavior: 'instant' });
  }
  return (
    <div className="wh-lab">
      <div className="wh-lab-controls">
        <nav className="wh-concepts" aria-label="Webhook design concepts">
          {CONCEPTS.map((concept, index) => <button type="button" key={concept.id} aria-pressed={active.id === concept.id} onClick={() => selectConcept(concept.id)}><span>0{index + 1}</span>{concept.name}</button>)}
        </nav>
        <label className="wh-concept-select"><span>Design</span><select aria-label="Webhook design concept" value={active.id} onChange={(event) => selectConcept(event.target.value)}>{CONCEPTS.map((concept, index) => <option key={concept.id} value={concept.id}>0{index + 1} · {concept.name}</option>)}</select></label>
        <button type="button" className="wh-btn wh-btn--quiet" onClick={model.reset}>Reset preview</button>
      </div>
      <p className="wh-concept-note">{active.note}</p>
      <Workspace key={active.id} model={model} concept={active} />
      <footer className="wh-lab-footer">
        <span className={`wh-preview-notice ${model.removedUser ? 'wh-preview-notice--action' : ''}`}><span role="status">{model.notice || 'Sample data · changes stay in this preview'}</span>{model.removedUser && <button type="button" className="wh-text-btn" onClick={model.undoUnwatch}>Undo unwatch</button>}</span>
        <label className="wh-check"><input type="checkbox" checked={!model.connected} onChange={model.toggleConnected} />Preview offline stream</label>
      </footer>
    </div>
  );
}
