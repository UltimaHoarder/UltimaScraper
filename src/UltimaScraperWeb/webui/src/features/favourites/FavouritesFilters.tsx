import { useEffect, useRef, useState } from 'react';

import { UsersFiltersModal } from '../users/components/UsersFiltersModal';
import type { UserFilterMap } from '../users/lib/usersUtils';
import { parseFavouriteFilters, availability, ranges, keys, noUserFilters } from './favouriteFilters';


export function FavouritesFilters({ params, onApply }: { params: URLSearchParams; onApply: (values: URLSearchParams) => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(new URLSearchParams());
  const [error, setError] = useState('');
  const trigger = useRef<HTMLButtonElement>(null);
  const close = () => { setOpen(false); trigger.current?.focus(); };
  useEffect(() => {
    if (!open) return;
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { setOpen(false); trigger.current?.focus(); } };
    document.addEventListener('keydown', escape);
    return () => document.removeEventListener('keydown', escape);
  }, [open]);
  const change = (key: string, value: string) => setDraft(previous => {
    const next = new URLSearchParams(previous);
    if (value) next.set(key, value); else next.delete(key);
    return next;
  });
  const values = parseFavouriteFilters(draft);
  const userFilters: UserFilterMap = { performer: values.performer ?? 'none', subscribed: values.subscribed ?? 'none' };
  const count = Object.keys(parseFavouriteFilters(params)).length;
  const apply = () => {
    for (const name of ranges) {
      const lower = draft.get('min_' + name), upper = draft.get('max_' + name);
      for (const value of [lower, upper]) if (value && (!Number.isFinite(Number(value)) || Number(value) < 0 || (name !== 'price' && !Number.isSafeInteger(Number(value))))) {
        setError('Enter valid non-negative prices and whole-number counts.'); return;
      }
      if (lower && upper && Number(lower) > Number(upper)) { setError('Minimum values must not exceed maximum values.'); return; }
    }
    const next = new URLSearchParams(params);
    for (const key of keys) { next.delete(key); const value = draft.get(key); if (value) next.set(key, value); }
    onApply(next); close();
  };
  return <>
    <button ref={trigger} type="button" className="users-toolbar__btn" aria-label={count ? 'Filters (' + count + ')' : 'Filters'} onClick={() => { setDraft(new URLSearchParams(params)); setError(''); setOpen(true); }}>
      Filters{count > 0 && ' (' + count + ')'}
    </button>
    <UsersFiltersModal isOpen={open} title="Favourite filters"
      help="Filter creators by their profile fields. On content tabs these filters match the author."
      clearActiveOnly={false} clearUserFilters={noUserFilters}
      onClearExtraFilters={() => { change('availability', ''); setError(''); }}
      extraFilters={<>
        <div className="content-library-filter-row"><span className="content-library-filter-name">Availability</span>
          <select aria-label="Favourite availability" value={draft.get('availability') ?? ''} onChange={event => change('availability', event.target.value)}>
            <option value="">All availability</option>{availability.map(value => <option key={value} value={value}>{value[0].toUpperCase() + value.slice(1)}</option>)}
          </select>
        </div>
        {error && <p role="alert">{error}</p>}
      </>}
      draftActiveOnly={values.active_only ?? false}
      onDraftActiveOnlyChange={value => change('active_only', value ? 'true' : '')}
      draftUserFilters={userFilters}
      onDraftUserFiltersChange={value => { change('performer', value.performer === 'none' ? '' : value.performer); change('subscribed', value.subscribed === 'none' ? '' : value.subscribed); }}
      draftSexFilter={values.sex ?? []} onDraftSexFilterChange={value => change('sex', value.join(','))}
      draftGenderFilter={values.gender ?? []} onDraftGenderFilterChange={value => change('gender', value.join(','))}
      draftProfileTypeFilter={values.profile_type ?? []} onDraftProfileTypeFilterChange={value => change('profile_type', value.join(','))}
      draftSexualContentFilter={values.sexual_content ?? []} onDraftSexualContentFilterChange={value => change('sexual_content', value.join(','))}
      draftMinPrice={draft.get('min_price') ?? ''} onDraftMinPriceChange={value => change('min_price', value)}
      draftMaxPrice={draft.get('max_price') ?? ''} onDraftMaxPriceChange={value => change('max_price', value)}
      draftMinPostCount={draft.get('min_post_count') ?? ''} onDraftMinPostCountChange={value => change('min_post_count', value)}
      draftMaxPostCount={draft.get('max_post_count') ?? ''} onDraftMaxPostCountChange={value => change('max_post_count', value)}
      draftMinImageCount={draft.get('min_image_count') ?? ''} onDraftMinImageCountChange={value => change('min_image_count', value)}
      draftMaxImageCount={draft.get('max_image_count') ?? ''} onDraftMaxImageCountChange={value => change('max_image_count', value)}
      draftMinVideoCount={draft.get('min_video_count') ?? ''} onDraftMinVideoCountChange={value => change('min_video_count', value)}
      draftMaxVideoCount={draft.get('max_video_count') ?? ''} onDraftMaxVideoCountChange={value => change('max_video_count', value)}
      onClose={close} onApply={apply} />
  </>;
}
