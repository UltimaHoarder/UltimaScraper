import { useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { createJob } from '../../api/jobs';
import { createOrderedPerformer } from '../../api/orders';
import { addToIgnoreList, addToWatchList, getEligibleAuths, removeFromIgnoreList, removeFromWatchList, updateUser } from '../../api/users';
import type { EligibleAuth, UserInfo, UserUpdateRequest } from '../../api/types/users';
import { useIdentityDraft } from '../user-profile/hooks/useIdentityDraft';
import { identityDraftFromUser, parseIdentityDraft } from '../user-profile/lib/identityDraft';

/** User actions only. Favourites owns its bounded archive-backed list queries. */
export function useFavouriteUserActions() {
  const client = useQueryClient();
  const [notice, setNotice] = useState<{ message: string; error: boolean } | null>(null);
  const report = (message: string, error = false) => setNotice({ message, error });
  const fail = (error: Error) => report(error.message, true);
  const [watched, setWatched] = useState(new Set<string>());
  const [ignored, setIgnored] = useState(new Set<string>());
  const [authTarget, setAuthTarget] = useState<UserInfo | null>(null);
  const [auths, setAuths] = useState<EligibleAuth[]>([]);
  const [resolvingAuth, setResolvingAuth] = useState(false);
  const authLock = useRef(false);
  const [editTarget, setEditTarget] = useState<UserInfo | null>(null);
  const [editName, setEditName] = useState('');
  const [editAlias, setEditAlias] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const identity = useIdentityDraft();
  const [lightbox, setLightbox] = useState<{ url: string | null; alt: string }>({ url: null, alt: 'Image preview' });
  const key = (user: UserInfo) => `${user.site}-${user.user_id}`;
  const create = useMutation({ mutationFn: createJob, onError: fail, onSuccess: data => {
    report(`Job "${data.job_name}" created successfully!`);
    void client.invalidateQueries({ queryKey: ['jobs'] });
  } });
  const dispatchScrape = (user: UserInfo, authId?: number) => create.mutate({
    job_name: `Scrape + Download @${user.username} (${user.site})`, created_by: 'webui',
    tasks: [{ task_type: 'scrape_and_download', params: { site: user.site, username: user.username,
      content_types: ['Posts', 'ArchivedPosts', 'Messages', 'Stories', 'Highlights', 'Profile'],
      rescrape_existing: true, ...(authId === undefined ? {} : { auth_id: authId }) } }],
  });
  const scrape = async (user: UserInfo) => {
    if (authLock.current || create.isPending) return;
    authLock.current = true;
    setResolvingAuth(true);
    try {
      const response = await getEligibleAuths(user.user_id, user.site);
      if (response.error) throw new Error(response.error);
      if (response.auths.length <= 1) dispatchScrape(user, response.auths[0]?.auth_id);
      else { setAuths(response.auths); setAuthTarget(user); }
    } catch (error) { fail(error instanceof Error ? error : new Error('Failed to fetch eligible auths')); }
    finally { authLock.current = false; setResolvingAuth(false); }
  };
  const subscribe = useMutation({ mutationFn: (user: UserInfo) => createOrderedPerformer({
    site: user.site, user_id: user.user_id, username: user.username, price: user.price, auto_execute: false,
  }), onError: fail, onSuccess: result => {
    report(result.success ? result.message || 'Subscription order queued' : result.error || 'Failed to subscribe', !result.success);
    void client.invalidateQueries({ queryKey: ['orders-performers'] });
  } });
  const watch = useMutation({ mutationFn: async (user: UserInfo) => {
    const result = await (watched.has(key(user)) ? removeFromWatchList : addToWatchList)(user.user_id, user.site);
    return { user, result };
  }, onError: fail, onSuccess: ({ user, result }) => {
    setWatched(previous => { const next = new Set(previous); if (result.watched) next.add(key(user)); else next.delete(key(user)); return next; });
    report(result.message);
    void client.invalidateQueries({ queryKey: ['watchList'] });
    void client.invalidateQueries({ queryKey: ['watchStats'] });
  } });
  const ignore = useMutation({ mutationFn: async (user: UserInfo) => {
    const result = await (ignored.has(key(user)) ? removeFromIgnoreList : addToIgnoreList)(user.user_id, user.site);
    return { user, result };
  }, onError: fail, onSuccess: ({ user, result }) => {
    setIgnored(previous => { const next = new Set(previous); if (result.ignored) next.add(key(user)); else next.delete(key(user)); return next; });
    report(result.message);
  } });
  const edit = useMutation({ mutationFn: async ({ user, payload }: { user: UserInfo; payload: UserUpdateRequest }) => {
    const result = await updateUser(user.user_id, user.site, payload);
    if (!result.success) throw new Error(result.error || 'Failed to update user');
    return result;
  }, onError: fail, onSuccess: () => {
    setEditTarget(null); report('User updated');
    for (const name of ['favourites-list', 'favourites-counts', 'users-list', 'users-stats', 'user-profile', 'user-aliases', 'subscriptions']) {
      void client.invalidateQueries({ queryKey: [name] });
    }
  } });
  const openEdit = (user: UserInfo) => {
    setEditTarget(user); setEditName(user.name ?? ''); setEditAlias('');
    setEditDescription(user.description ?? ''); identity.setDraft(identityDraftFromUser(user));
  };
  const saveEdit = () => {
    if (!editTarget || edit.isPending) return;
    const parsed = parseIdentityDraft(identity.draft);
    if (!parsed.ok) { report(parsed.error, true); return; }
    edit.mutate({ user: editTarget, payload: { name: editName.trim() || null, alias: editAlias.trim() || null,
      description: editDescription.trim() || null, ...parsed.values, ai_assisted: false, verified: true } });
  };
  return { notice, setNotice, watched, ignored, key, scrape, subscribe, watch, ignore, create, resolvingAuth,
    authTarget, auths, closeAuth: () => setAuthTarget(null), selectAuth: (authId: number) => {
      if (!authTarget || create.isPending) return;
      dispatchScrape(authTarget, authId); setAuthTarget(null);
    }, editTarget, editName, editAlias, editDescription, setEditName, setEditAlias, setEditDescription,
    identityFields: identity.fields, edit, openEdit, saveEdit, closeEdit: () => setEditTarget(null),
    lightbox, openLightbox: (url: string | null, alt = 'Image preview') => setLightbox({ url, alt }),
    closeLightbox: () => setLightbox(current => ({ ...current, url: null })) };
}
