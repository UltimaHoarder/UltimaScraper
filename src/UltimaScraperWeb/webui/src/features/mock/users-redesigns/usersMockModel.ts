import { useState } from 'react';
import type { UserInfo } from '../../../api/types/users';

export interface MockUser extends UserInfo {
  storage_bytes?: number;
  unscraped_posts?: number;
  confidence?: number;
  tags?: string[];
}

export function formatBytes(bytes?: number): string {
  if (!bytes || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

export function getFreshnessStatus(user: MockUser): 'fresh' | 'overdue' | 'unscraped' | 'idle' {
  if (!user.downloaded_at) return 'unscraped';
  const lastScraped = new Date(user.downloaded_at).getTime();
  const daysDiff = (Date.now() - lastScraped) / (1000 * 60 * 60 * 24);
  if (daysDiff > 7) return 'overdue';
  return 'fresh';
}

function seedUsers(): MockUser[] {
  return [
    {
      id: 101,
      user_id: 101,
      username: 'luna.studio',
      name: 'Luna Ray',
      site: 'onlyfans',
      price: 9.99,
      post_count: 1420,
      media_count: 4262,
      image_count: 3850,
      video_count: 412,
      sex: 0,
      gender: 0,
      profile_type: 0,
      sexual_content: 0,
      partner_sex: null,
      partner_gender: null,
      ai_assisted: false,
      verified: true,
      description: 'Exclusive studio photography, weekly lifestyle sets, and behind-the-scenes vlogs.',
      avatar_url: 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=256&h=256&q=80',
      header_url: 'https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1200&h=400&q=80',
      favorite: true,
      is_active: true,
      is_subscribed: true,
      is_pending_order: false,
      downloaded_at: '2026-10-11T14:20:00Z',
      last_checked_at: '2026-10-13T04:15:00Z',
      storage_bytes: 48318382080,
      unscraped_posts: 0,
      confidence: 0.98,
      tags: ['Cosplay', 'Studio', 'Portrait'],
    },
    {
      id: 102,
      user_id: 102,
      username: 'ivy.archive',
      name: 'Ivy Winters',
      site: 'fansly',
      price: 0.0,
      post_count: 540,
      media_count: 1288,
      image_count: 1200,
      video_count: 88,
      sex: 0,
      gender: 0,
      profile_type: 0,
      sexual_content: 1,
      partner_sex: null,
      partner_gender: null,
      ai_assisted: false,
      verified: true,
      description: 'Daily aesthetic moodboards, editorial concepts, and visual stories.',
      avatar_url: 'https://images.unsplash.com/photo-1517841905240-472988babdf9?auto=format&fit=crop&w=256&h=256&q=80',
      header_url: 'https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1200&h=400&q=80',
      favorite: false,
      is_active: true,
      is_subscribed: true,
      is_pending_order: false,
      downloaded_at: '2026-10-12T20:30:00Z',
      last_checked_at: '2026-10-13T05:00:00Z',
      storage_bytes: 14200492000,
      unscraped_posts: 0,
      confidence: 0.94,
      tags: ['Editorial', 'Free Feed', 'Art'],
    },
    {
      id: 103,
      user_id: 103,
      username: 'nova.notes',
      name: 'Nova Chen',
      site: 'onlyfans',
      price: 14.99,
      post_count: 320,
      media_count: 935,
      image_count: 890,
      video_count: 45,
      sex: 2,
      gender: 2,
      profile_type: 0,
      sexual_content: 4,
      partner_sex: null,
      partner_gender: null,
      ai_assisted: false,
      verified: true,
      description: 'Queer electronic music producer sharing synth walkthroughs and artistic visuals.',
      avatar_url: 'https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?auto=format&fit=crop&w=256&h=256&q=80',
      header_url: 'https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?auto=format&fit=crop&w=1200&h=400&q=80',
      favorite: true,
      is_active: true,
      is_subscribed: false,
      is_pending_order: false,
      downloaded_at: null,
      last_checked_at: '2026-10-10T12:00:00Z',
      storage_bytes: 0,
      unscraped_posts: 320,
      confidence: 0.88,
      tags: ['Music', 'Visuals', 'Queer'],
    },
    {
      id: 104,
      user_id: 104,
      username: 'sage.frames',
      name: 'Sage & Alex',
      site: 'onlyfans',
      price: 19.99,
      post_count: 890,
      media_count: 2760,
      image_count: 2450,
      video_count: 310,
      sex: 0,
      gender: 0,
      profile_type: 1,
      sexual_content: 3,
      partner_sex: 1,
      partner_gender: 1,
      ai_assisted: false,
      verified: true,
      description: 'Traveling couple documenting adventures across 40 countries.',
      avatar_url: 'https://images.unsplash.com/photo-1524504388940-b1c1722653e1?auto=format&fit=crop&w=256&h=256&q=80',
      header_url: 'https://images.unsplash.com/photo-1469854523086-cc02fe5d8800?auto=format&fit=crop&w=1200&h=400&q=80',
      favorite: false,
      is_active: true,
      is_subscribed: true,
      is_pending_order: false,
      downloaded_at: '2026-09-28T11:15:00Z',
      last_checked_at: '2026-10-12T19:00:00Z',
      storage_bytes: 39820100000,
      unscraped_posts: 48,
      confidence: 0.96,
      tags: ['Couple', 'Travel', 'Bisexual'],
    },
    {
      id: 105,
      user_id: 105,
      username: 'mira.daylight',
      name: 'Mira S.',
      site: 'fansly',
      price: 4.99,
      post_count: 610,
      media_count: 1700,
      image_count: 1580,
      video_count: 120,
      sex: 0,
      gender: 0,
      profile_type: 0,
      sexual_content: 0,
      partner_sex: null,
      partner_gender: null,
      ai_assisted: false,
      verified: true,
      description: 'Natural light enthusiast, golden hour photography and fitness journaling.',
      avatar_url: 'https://images.unsplash.com/photo-1494790108377-be9c29b29330?auto=format&fit=crop&w=256&h=256&q=80',
      header_url: 'https://images.unsplash.com/photo-1470240731273-7821a6eeb6bd?auto=format&fit=crop&w=1200&h=400&q=80',
      favorite: true,
      is_active: true,
      is_subscribed: false,
      is_pending_order: false,
      downloaded_at: '2026-10-12T08:40:00Z',
      last_checked_at: '2026-10-13T02:00:00Z',
      storage_bytes: 18400000000,
      unscraped_posts: 2,
      confidence: 0.99,
      tags: ['Fitness', 'Outdoor', 'Solo'],
    },
    {
      id: 106,
      user_id: 106,
      username: 'atlas.journal',
      name: 'Atlas Vance',
      site: 'fansly',
      price: 0.0,
      post_count: 180,
      media_count: 435,
      image_count: 420,
      video_count: 15,
      sex: 1,
      gender: 1,
      profile_type: 0,
      sexual_content: 2,
      partner_sex: null,
      partner_gender: null,
      ai_assisted: true,
      verified: false,
      description: 'AI-assisted architectural renderings and digital futurism modeling.',
      avatar_url: 'https://images.unsplash.com/photo-1500648767791-00dcc994a43e?auto=format&fit=crop&w=256&h=256&q=80',
      header_url: 'https://images.unsplash.com/photo-1451187580459-43490279c0fa?auto=format&fit=crop&w=1200&h=400&q=80',
      favorite: false,
      is_active: false,
      is_subscribed: false,
      is_pending_order: false,
      downloaded_at: null,
      last_checked_at: '2026-10-05T09:00:00Z',
      storage_bytes: 0,
      unscraped_posts: 180,
      confidence: 0.72,
      tags: ['AI-Art', 'Architecture', 'Solo'],
    },
    {
      id: 107,
      user_id: 107,
      username: 'olive.room',
      name: 'Olive Garcia',
      site: 'onlyfans',
      price: 12.0,
      post_count: 950,
      media_count: 2290,
      image_count: 2100,
      video_count: 190,
      sex: 0,
      gender: 0,
      profile_type: 0,
      sexual_content: 3,
      partner_sex: null,
      partner_gender: null,
      ai_assisted: false,
      verified: true,
      description: 'Intimate portraits, vintage aesthetics, and film camera scans.',
      avatar_url: 'https://images.unsplash.com/photo-1544005313-94ddf0286df2?auto=format&fit=crop&w=256&h=256&q=80',
      header_url: 'https://images.unsplash.com/photo-1513151233558-d860c5398176?auto=format&fit=crop&w=1200&h=400&q=80',
      favorite: false,
      is_active: true,
      is_subscribed: false,
      is_pending_order: false,
      downloaded_at: '2026-09-12T16:00:00Z',
      last_checked_at: '2026-10-11T14:00:00Z',
      storage_bytes: 25400000000,
      unscraped_posts: 72,
      confidence: 0.95,
      tags: ['Film', 'Vintage', 'Solo'],
    },
    {
      id: 108,
      user_id: 108,
      username: 'phoenix.duo',
      name: 'Phoenix Collab',
      site: 'onlyfans',
      price: 24.99,
      post_count: 1120,
      media_count: 4730,
      image_count: 4200,
      video_count: 530,
      sex: 1,
      gender: 1,
      profile_type: 2,
      sexual_content: 2,
      partner_sex: 1,
      partner_gender: 1,
      ai_assisted: false,
      verified: true,
      description: 'High-production male group fitness, acrobatics, and performance art.',
      avatar_url: 'https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?auto=format&fit=crop&w=256&h=256&q=80',
      header_url: 'https://images.unsplash.com/photo-1517838277536-f5f99be501cd?auto=format&fit=crop&w=1200&h=400&q=80',
      favorite: true,
      is_active: true,
      is_subscribed: true,
      is_pending_order: false,
      downloaded_at: '2026-10-10T18:00:00Z',
      last_checked_at: '2026-10-13T03:30:00Z',
      storage_bytes: 68900000000,
      unscraped_posts: 12,
      confidence: 0.97,
      tags: ['Athletic', 'Group', 'Gay'],
    },
    {
      id: 109,
      user_id: 109,
      username: 'kova.synth',
      name: 'Kova Synthetic',
      site: 'fansly',
      price: 0.0,
      post_count: 240,
      media_count: 814,
      image_count: 780,
      video_count: 34,
      sex: -1,
      gender: -1,
      profile_type: -1,
      sexual_content: -1,
      partner_sex: null,
      partner_gender: null,
      ai_assisted: true,
      verified: false,
      description: 'Fully synthetic virtual persona generated with high-definition neural renderers.',
      avatar_url: 'https://images.unsplash.com/photo-1531746020798-e6953c6e8e04?auto=format&fit=crop&w=256&h=256&q=80',
      header_url: 'https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&w=1200&h=400&q=80',
      favorite: false,
      is_active: true,
      is_subscribed: false,
      is_pending_order: false,
      downloaded_at: null,
      last_checked_at: '2026-10-12T11:00:00Z',
      storage_bytes: 0,
      unscraped_posts: 240,
      confidence: 0.55,
      tags: ['Virtual', 'AI', 'Unclassified'],
    },
    {
      id: 110,
      user_id: 110,
      username: 'echo.mirage',
      name: 'Echo Mirage',
      site: 'onlyfans',
      price: 7.99,
      post_count: 430,
      media_count: 1195,
      image_count: 1100,
      video_count: 95,
      sex: 0,
      gender: 0,
      profile_type: 0,
      sexual_content: 0,
      partner_sex: null,
      partner_gender: null,
      ai_assisted: false,
      verified: true,
      description: 'Neon nightlife, cyber aesthetics, and electronic stage visuals.',
      avatar_url: 'https://images.unsplash.com/photo-1529626455594-4ff0802cfb7e?auto=format&fit=crop&w=256&h=256&q=80',
      header_url: 'https://images.unsplash.com/photo-1508739773434-c26b3d09e071?auto=format&fit=crop&w=1200&h=400&q=80',
      favorite: false,
      is_active: true,
      is_subscribed: false,
      is_pending_order: false,
      downloaded_at: '2026-10-04T12:00:00Z',
      last_checked_at: '2026-10-12T22:00:00Z',
      storage_bytes: 16200000000,
      unscraped_posts: 35,
      confidence: 0.91,
      tags: ['Cyber', 'Neon', 'Solo'],
    },
  ];
}

export interface MockLoadout {
  id: string;
  name: string;
  is_default?: boolean;
  site?: string;
  status?: string;
  searchIdentifier?: string;
  searchDescription?: string;
  minPrice?: string;
  maxPrice?: string;
  minPostCount?: string;
}

export const SAMPLE_LOADOUTS: MockLoadout[] = [
  { id: 'free-feed', name: 'Free Exploratory', status: 'free' },
  { id: 'vip-subs', name: 'VIP Subscribers', status: 'subscribed', minPrice: '10' },
  { id: 'overdue-syncs', name: 'Overdue Syncs', status: 'unscraped' },
  { id: 'onlyfans-all', name: 'OnlyFans Roster', site: 'onlyfans' },
  { id: 'fansly-all', name: 'Fansly Roster', site: 'fansly' },
];

export function useUsersMockModel(initialSelectedId = 101) {
  const [users, setUsers] = useState<MockUser[]>(seedUsers);
  const [selectedId, setSelectedId] = useState<number>(initialSelectedId);
  const [selectedUserIds, setSelectedUserIds] = useState<Set<number>>(new Set());
  const [watchedKeys, setWatchedKeys] = useState<Set<number>>(new Set([101, 102, 104, 108]));
  const [ignoredKeys, setIgnoredKeys] = useState<Set<number>>(new Set());
  const [searchIdentifier, setSearchIdentifier] = useState('');
  const [searchDescription, setSearchDescription] = useState('');
  const [siteFilter, setSiteFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [sortBy, setSortBy] = useState<string>('posts');
  const [minPrice, setMinPrice] = useState('');
  const [maxPrice, setMaxPrice] = useState('');
  const [minPostCount, setMinPostCount] = useState('');
  const [minImageCount, setMinImageCount] = useState('');
  const [minVideoCount, setMinVideoCount] = useState('');
  const [loadouts, setLoadouts] = useState<MockLoadout[]>(SAMPLE_LOADOUTS);
  const [activeLoadoutName, setActiveLoadoutName] = useState<string>('');
  const [isLoadoutModalOpen, setIsLoadoutModalOpen] = useState(false);
  const [isFiltersModalOpen, setIsFiltersModalOpen] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const selectedUser = users.find((user) => user.id === selectedId) ?? users[0];

  const visibleUsers = users
    .filter((user) => {
      // 1. Search by Identifier (Handle, ID, Display Name)
      if (searchIdentifier.trim()) {
        const q = searchIdentifier.trim().toLowerCase();
        const matchesHandle = user.username.toLowerCase().includes(q);
        const matchesName = (user.name ?? '').toLowerCase().includes(q);
        const matchesId = String(user.user_id).includes(q) || String(user.id).includes(q);
        if (!matchesHandle && !matchesName && !matchesId) return false;
      }
      // 2. Search by Description (Bio text)
      if (searchDescription.trim()) {
        const q = searchDescription.trim().toLowerCase();
        const matchesBio = (user.description ?? '').toLowerCase().includes(q);
        if (!matchesBio) return false;
      }
      // 3. Platform & status
      if (siteFilter !== 'all' && user.site !== siteFilter) return false;
      if (statusFilter === 'active' && !user.is_active) return false;
      if (statusFilter === 'subscribed' && !user.is_subscribed) return false;
      if (statusFilter === 'favorite' && !user.favorite) return false;
      if (statusFilter === 'watched' && !watchedKeys.has(user.id)) return false;
      if (statusFilter === 'free' && user.price > 0) return false;
      if (statusFilter === 'paid' && user.price === 0) return false;
      if (statusFilter === 'unscraped' && user.downloaded_at !== null) return false;
      // 4. Numeric range filters
      if (minPrice && user.price < Number(minPrice)) return false;
      if (maxPrice && user.price > Number(maxPrice)) return false;
      if (minPostCount && user.post_count < Number(minPostCount)) return false;
      if (minImageCount && user.image_count < Number(minImageCount)) return false;
      if (minVideoCount && user.video_count < Number(minVideoCount)) return false;
      return true;
    })
    .sort((a, b) => {
      if (sortBy === 'posts') return b.post_count - a.post_count;
      if (sortBy === 'media') return b.media_count - a.media_count;
      if (sortBy === 'price_desc') return b.price - a.price;
      if (sortBy === 'price_asc') return a.price - b.price;
      if (sortBy === 'name') return a.username.localeCompare(b.username);
      if (sortBy === 'recent') {
        const dateA = a.last_checked_at ? new Date(a.last_checked_at).getTime() : 0;
        const dateB = b.last_checked_at ? new Date(b.last_checked_at).getTime() : 0;
        return dateB - dateA;
      }
      return 0;
    });

  const activeFilterCount =
    (searchDescription.trim() ? 1 : 0) +
    (minPrice ? 1 : 0) +
    (maxPrice ? 1 : 0) +
    (minPostCount ? 1 : 0) +
    (minImageCount ? 1 : 0) +
    (minVideoCount ? 1 : 0);

  // Analytics
  const totalPosts = users.reduce((sum, u) => sum + u.post_count, 0);
  const totalMedia = users.reduce((sum, u) => sum + u.media_count, 0);
  const totalStorage = users.reduce((sum, u) => sum + (u.storage_bytes ?? 0), 0);
  const paidUsers = users.filter((u) => u.price > 0);
  const avgPrice = paidUsers.length ? paidUsers.reduce((sum, u) => sum + u.price, 0) / paidUsers.length : 0;
  const activeCount = users.filter((u) => u.is_active).length;
  const favoriteCount = users.filter((u) => u.favorite).length;
  const unscrapedCount = users.filter((u) => !u.downloaded_at).length;

  const showToast = (msg: string) => {
    setNotice(msg);
  };

  const toggleSelect = (id: number) => {
    setSelectedUserIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAll = () => {
    if (selectedUserIds.size === visibleUsers.length) {
      setSelectedUserIds(new Set());
    } else {
      setSelectedUserIds(new Set(visibleUsers.map((u) => u.id)));
    }
  };

  const clearSelection = () => {
    setSelectedUserIds(new Set());
  };

  const toggleFavorite = (id: number) => {
    setUsers((current) =>
      current.map((u) => {
        if (u.id === id) {
          const nextFav = !u.favorite;
          showToast(`@${u.username} ${nextFav ? 'added to favorites' : 'removed from favorites'}`);
          return { ...u, favorite: nextFav };
        }
        return u;
      }),
    );
  };

  const toggleWatch = (id: number) => {
    const user = users.find((u) => u.id === id);
    setWatchedKeys((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
        showToast(`@${user?.username ?? id} unpinned from watch list`);
      } else {
        next.add(id);
        showToast(`@${user?.username ?? id} added to live watch list`);
      }
      return next;
    });
  };

  const toggleIgnore = (id: number) => {
    const user = users.find((u) => u.id === id);
    setIgnoredKeys((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
        showToast(`@${user?.username ?? id} un-ignored`);
      } else {
        next.add(id);
        showToast(`@${user?.username ?? id} marked as ignored`);
      }
      return next;
    });
  };

  const toggleSubscribe = (id: number) => {
    setUsers((current) =>
      current.map((u) => {
        if (u.id === id) {
          const nextSub = !u.is_subscribed;
          showToast(`Subscription status toggled for @${u.username}`);
          return { ...u, is_subscribed: nextSub };
        }
        return u;
      }),
    );
  };

  const dispatchScrape = (id: number) => {
    const user = users.find((u) => u.id === id);
    if (!user) return;
    setUsers((current) =>
      current.map((u) => {
        if (u.id === id) {
          return {
            ...u,
            downloaded_at: new Date().toISOString(),
            last_checked_at: new Date().toISOString(),
            unscraped_posts: 0,
          };
        }
        return u;
      }),
    );
    showToast(`Scrape job queued for @${user.username} (${user.site})`);
  };

  const bulkScrape = () => {
    const count = selectedUserIds.size;
    if (count === 0) return;
    setUsers((current) =>
      current.map((u) => {
        if (selectedUserIds.has(u.id)) {
          return {
            ...u,
            downloaded_at: new Date().toISOString(),
            last_checked_at: new Date().toISOString(),
            unscraped_posts: 0,
          };
        }
        return u;
      }),
    );
    showToast(`Dispatched bulk scrape job for ${count} selected creator${count === 1 ? '' : 's'}`);
    clearSelection();
  };

  const bulkWatch = (watchState: boolean) => {
    const count = selectedUserIds.size;
    if (count === 0) return;
    setWatchedKeys((prev) => {
      const next = new Set(prev);
      selectedUserIds.forEach((id) => {
        if (watchState) next.add(id);
        else next.delete(id);
      });
      return next;
    });
    showToast(`${watchState ? 'Added' : 'Removed'} ${count} creator${count === 1 ? '' : 's'} to watch list`);
    clearSelection();
  };

  const bulkIgnore = (ignoreState: boolean) => {
    const count = selectedUserIds.size;
    if (count === 0) return;
    setIgnoredKeys((prev) => {
      const next = new Set(prev);
      selectedUserIds.forEach((id) => {
        if (ignoreState) next.add(id);
        else next.delete(id);
      });
      return next;
    });
    showToast(`${ignoreState ? 'Ignored' : 'Un-ignored'} ${count} creator${count === 1 ? '' : 's'}`);
    clearSelection();
  };

  const updateUserIdentity = (
    id: number,
    patch: { sex?: number; gender?: number; profile_type?: number; sexual_content?: number; ai_assisted?: boolean; confidence?: number },
  ) => {
    setUsers((current) =>
      current.map((u) => {
        if (u.id === id) {
          showToast(`Updated taxonomy for @${u.username}`);
          return { ...u, ...patch, confidence: patch.confidence ?? 1.0 };
        }
        return u;
      }),
    );
  };

  const bulkSetIdentity = (
    patch: { sex?: number; gender?: number; profile_type?: number; sexual_content?: number; ai_assisted?: boolean },
  ) => {
    const count = selectedUserIds.size;
    if (count === 0) return;
    setUsers((current) =>
      current.map((u) => {
        if (selectedUserIds.has(u.id)) {
          return { ...u, ...patch, confidence: 1.0 };
        }
        return u;
      }),
    );
    showToast(`Applied taxonomy preset to ${count} creators`);
    clearSelection();
  };

  const applyLoadout = (loadout: MockLoadout) => {
    setActiveLoadoutName(loadout.name);
    if (loadout.site) setSiteFilter(loadout.site);
    if (loadout.status) setStatusFilter(loadout.status);
    if (loadout.searchIdentifier !== undefined) setSearchIdentifier(loadout.searchIdentifier);
    if (loadout.searchDescription !== undefined) setSearchDescription(loadout.searchDescription);
    if (loadout.minPrice !== undefined) setMinPrice(loadout.minPrice);
    if (loadout.maxPrice !== undefined) setMaxPrice(loadout.maxPrice);
    if (loadout.minPostCount !== undefined) setMinPostCount(loadout.minPostCount);
    setIsLoadoutModalOpen(false);
    showToast(`Applied loadout "${loadout.name}"`);
  };

  const clearLoadout = () => {
    setActiveLoadoutName('');
    showToast('Cleared active loadout');
  };

  const resetFilters = () => {
    setMinPrice('');
    setMaxPrice('');
    setMinPostCount('');
    setMinImageCount('');
    setMinVideoCount('');
    setSearchDescription('');
    showToast('Advanced filters reset');
  };

  const reset = () => {
    setUsers(seedUsers());
    setSelectedId(101);
    setSelectedUserIds(new Set());
    setWatchedKeys(new Set([101, 102, 104, 108]));
    setIgnoredKeys(new Set());
    setSearchIdentifier('');
    setSearchDescription('');
    setMinPrice('');
    setMaxPrice('');
    setMinPostCount('');
    setMinImageCount('');
    setMinVideoCount('');
    setActiveLoadoutName('');
    setIsLoadoutModalOpen(false);
    setIsFiltersModalOpen(false);
    setSiteFilter('all');
    setStatusFilter('all');
    setSortBy('posts');
    setNotice('Sample creator roster reset.');
  };

  return {
    users,
    visibleUsers,
    selectedUser,
    selectedId,
    setSelectedId,
    selectedUserIds,
    watchedKeys,
    ignoredKeys,
    searchIdentifier,
    setSearchIdentifier,
    searchDescription,
    setSearchDescription,
    siteFilter,
    setSiteFilter,
    statusFilter,
    setStatusFilter,
    sortBy,
    setSortBy,
    minPrice,
    setMinPrice,
    maxPrice,
    setMaxPrice,
    minPostCount,
    setMinPostCount,
    minImageCount,
    setMinImageCount,
    minVideoCount,
    setMinVideoCount,
    loadouts,
    setLoadouts,
    activeLoadoutName,
    setActiveLoadoutName,
    applyLoadout,
    clearLoadout,
    isLoadoutModalOpen,
    setIsLoadoutModalOpen,
    isFiltersModalOpen,
    setIsFiltersModalOpen,
    activeFilterCount,
    resetFilters,
    notice,
    setNotice,
    // Metrics
    totalPosts,
    totalMedia,
    totalStorage,
    avgPrice,
    activeCount,
    favoriteCount,
    unscrapedCount,
    // Actions
    toggleSelect,
    selectAll,
    clearSelection,
    toggleFavorite,
    toggleWatch,
    toggleIgnore,
    toggleSubscribe,
    dispatchScrape,
    bulkScrape,
    bulkWatch,
    bulkIgnore,
    updateUserIdentity,
    bulkSetIdentity,
    reset,
  };
}

export type UsersMockModel = ReturnType<typeof useUsersMockModel>;
