import { useState } from 'react';
import type { WebhookInfo, WatchedUserInfo } from '../../../api/types/webhooks';
import type { WebhookMessage } from '../../../hooks/useWebhookStream';
import { filterWebhookMessages, type CategoryFilter, type SiteKey } from '../../webhooks/lib/webhooksUtils';

export interface MockRoute extends WebhookInfo {
  id: string;
  site: SiteKey;
  kind: 'Auth' | 'Download';
}

export const MOCK_ROUTES: MockRoute[] = [
  { id: 'of-auth', site: 'onlyfans', kind: 'Auth', active: true, url: 'https://hooks.example.invalid/onlyfans/auth', hide_info: ['cookie', 'authorization'] },
  { id: 'of-download', site: 'onlyfans', kind: 'Download', active: true, url: 'https://hooks.example.invalid/onlyfans/download', hide_info: ['directory'] },
  { id: 'fy-auth', site: 'fansly', kind: 'Auth', active: false, url: null, hide_info: [] },
  { id: 'fy-download', site: 'fansly', kind: 'Download', active: true, url: 'https://hooks.example.invalid/fansly/download', hide_info: ['directory'] },
];

const PEOPLE: WatchedUserInfo[] = [
  { id: 1042, username: 'luna.studio', site: 'onlyfans', watched: true, downloaded_at: '2026-10-12T09:42:00Z', created_at: '2026-10-01T09:00:00Z' },
  { id: 2086, username: 'ivy.archive', site: 'fansly', watched: true, downloaded_at: '2026-10-11T18:20:00Z', created_at: '2026-10-02T09:00:00Z' },
  { id: 3071, username: 'nova.notes', site: 'onlyfans', watched: true, downloaded_at: null, created_at: '2026-10-12T08:15:00Z' },
  { id: 4208, username: 'sage.frames', site: 'onlyfans', watched: true, downloaded_at: '2026-10-10T14:12:00Z', created_at: '2026-10-03T09:00:00Z' },
  { id: 5109, username: 'mira.daylight', site: 'fansly', watched: true, downloaded_at: '2026-10-12T08:40:00Z', created_at: '2026-10-04T09:00:00Z' },
  { id: 6212, username: 'atlas.journal', site: 'fansly', watched: false, downloaded_at: null, created_at: '2026-10-05T09:00:00Z' },
  { id: 7340, username: 'olive.room', site: 'onlyfans', watched: false, downloaded_at: null, created_at: '2026-10-05T09:00:00Z' },
];

// Fixed fixtures mirror the message/category contract, with no invented delivery metrics.
const MESSAGES: WebhookMessage[] = [
  { id: 'evt-08', receivedAt: '2026-10-12T09:42:18Z', category: 'usapi', event: 'chat_message', eventType: 'new_message', payload: { type: 'chat_message', site: 'onlyfans', user_id: 1042, message: 'A new studio update is available.', source_id: 'onlyfans:ws:1042' } },
  { id: 'evt-07', receivedAt: '2026-10-12T09:41:54Z', category: 'backend', event: 'subscription_processing', payload: { type: 'subscription_processing', site: 'fansly', user_id: 2086, username: 'ivy.archive', status: 'started' } },
  { id: 'evt-06', receivedAt: '2026-10-12T09:40:32Z', category: 'usapi', event: 'subscription_added', payload: { type: 'subscription_added', site: 'onlyfans', user_id: 3071, username: 'nova.notes' } },
  { id: 'evt-05', receivedAt: '2026-10-12T09:39:12Z', category: 'backend', event: 'webhook', eventType: 'auth', payload: { type: 'webhook', event_type: 'auth', site: 'onlyfans', auth_id: 12, active: true } },
  { id: 'evt-04', receivedAt: '2026-10-12T09:38:46Z', category: 'system', event: 'system_health', payload: { type: 'system_health', status: 'healthy' } },
  { id: 'evt-03', receivedAt: '2026-10-12T09:37:21Z', category: 'usapi', event: 'websocket_message', eventType: 'post_update', payload: { type: 'websocket_message', site: 'fansly', user_id: 5109, event_type: 'post_update' } },
  { id: 'evt-02', receivedAt: '2026-10-12T09:35:40Z', category: 'backend', event: 'job_completed', payload: { type: 'job_completed', job_id: 'sample-job-1042', status: 'completed' } },
  { id: 'evt-01', receivedAt: '2026-10-12T09:34:06Z', category: 'system', event: 'queue_depth', payload: { type: 'queue_depth', pending: 4, running: 2 } },
];

export function useWebhooksMockModel() {
  const [messages, setMessages] = useState(MESSAGES);
  const [users, setUsers] = useState(PEOPLE.filter((user) => user.watched));
  const [paused, setPaused] = useState(false);
  const [connected, setConnected] = useState(true);
  const [category, setCategory] = useState<CategoryFilter>('all');
  const [query, setQuery] = useState('');
  const [showAll, setShowAll] = useState(false);
  const [selectedMessageId, setSelectedMessageId] = useState(MESSAGES[0].id);
  const [selectedRouteId, setSelectedRouteId] = useState(MOCK_ROUTES[0].id);
  const [watchSite, setWatchSite] = useState('all');
  const [watchQuery, setWatchQuery] = useState('');
  const [addQuery, setAddQuery] = useState('');
  const [addSite, setAddSite] = useState('onlyfans');
  const [notice, setNotice] = useState('');
  const [removedUser, setRemovedUser] = useState<WatchedUserInfo | null>(null);
  const filteredMessages = filterWebhookMessages(messages, category, showAll, query);
  const selectedMessage = filteredMessages.find((item) => item.id === selectedMessageId) ?? filteredMessages[0];
  const selectedRoute = MOCK_ROUTES.find((item) => item.id === selectedRouteId) ?? MOCK_ROUTES[0];
  const filteredUsers = users.filter((user) => (watchSite === 'all' || user.site === watchSite) && `${user.username} ${user.id}`.toLowerCase().includes(watchQuery.toLowerCase()));
  const candidates = addQuery.trim() ? PEOPLE.filter((person) => person.site === addSite && `${person.username} ${person.id}`.toLowerCase().includes(addQuery.toLowerCase()) && !users.some((user) => user.site === person.site && user.id === person.id)) : [];

  function reset() {
    setMessages(MESSAGES); setUsers(PEOPLE.filter((user) => user.watched));
    setPaused(false); setConnected(true); setCategory('all'); setQuery(''); setShowAll(false);
    setSelectedMessageId(MESSAGES[0].id); setSelectedRouteId(MOCK_ROUTES[0].id);
    setWatchSite('all'); setWatchQuery(''); setAddQuery(''); setAddSite('onlyfans'); setRemovedUser(null); setNotice('Sample data reset.');
  }

  return {
    isPreview: true, routes: MOCK_ROUTES, messages, filteredMessages, selectedMessage, category, setCategory, query, setQuery, showAll, setShowAll,
    setSelectedMessageId, selectedRoute, setSelectedRouteId, users, filteredUsers, paused, connected,
    watchSite, setWatchSite, watchQuery, setWatchQuery, addQuery, setAddQuery, addSite, setAddSite, candidates,
    notice, reset, removedUser,
    undoUnwatch: () => {
      if (!removedUser) return;
      setUsers((current) => current.some((user) => user.id === removedUser.id && user.site === removedUser.site) ? current : [...current, removedUser]);
      setNotice(`@${removedUser.username} restored to the sample watch list.`);
      setRemovedUser(null);
    },
    toggleConnected: () => setConnected((value) => !value),
    clearMessages: () => { setMessages([]); setNotice('Sample messages cleared from this preview.'); },
    togglePaused: () => { setPaused(!paused); setNotice(paused ? 'Sample watch list resumed.' : 'Sample watch list paused.'); },
    unwatch: (person: WatchedUserInfo) => { setUsers(users.filter((user) => user.id !== person.id || user.site !== person.site)); setRemovedUser(person); setNotice(`@${person.username} removed from the sample watch list.`); },
    watch: (person: WatchedUserInfo) => { setUsers([...users, { ...person, watched: true }]); setAddQuery(''); setNotice(`@${person.username} added to the sample watch list.`); },
  };
}

export type WebhooksMockModel = ReturnType<typeof useWebhooksMockModel>;
