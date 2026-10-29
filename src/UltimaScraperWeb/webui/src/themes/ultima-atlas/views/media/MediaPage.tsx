import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useInfiniteQuery, type InfiniteData } from '@tanstack/react-query';
import { browseMedia } from '../../../../api/database';
import {
  browserSupportsWidevine,
  getDrmLicenseUrl,
  getDrmManifestUrl,
  getMediaFileUrl,
} from '../../../../api/media';
import type { MediaBrowserResponse, MediaItem as DatabaseMediaItem } from '../../../../api/types/database';
import { LazyVideoPlayer } from '../../../../components/LazyVideoPlayer';
import {
  OperationsHero,
  OperationsNotice,
  OperationsState,
} from '../../patterns/OperationsChrome';
import './MediaPage.css';

interface MediaItem {
  id: string;
  numericId: number;
  type: 'image' | 'video';
  url: string;
  filename: string;
  size: number;
  site: string;
  drm: boolean;
}

export function MediaPage() {
  const [site, setSite] = useState<'all' | 'onlyfans' | 'fansly'>('all');
  const [typeFilter, setTypeFilter] = useState<'all' | 'image' | 'video'>('all');
  const [selectedItem, setSelectedItem] = useState<MediaItem | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const pageSize = 30;

  const toMediaItem = useCallback((item: DatabaseMediaItem): MediaItem | null => {
    const type = (item.media_type || '').toLowerCase();
    if (type && type !== 'image' && type !== 'video') return null;

    return {
      id: String(item.id),
      numericId: item.id,
      type: type === 'video' ? 'video' : 'image',
      url: getMediaFileUrl(item.site, item.id),
      filename: item.filename || 'media-' + item.id,
      size: item.size || 0,
      site: item.site,
      drm: Boolean(item.drm),
    };
  }, []);

  const {
    data,
    isLoading,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery<MediaBrowserResponse, Error, InfiniteData<MediaBrowserResponse>, (string | number)[], number>({
    queryKey: ['media', pageSize, site],
    initialPageParam: 1,
    queryFn: async ({ pageParam }) => {
      const response = await browseMedia(
        site === 'all' ? undefined : site,
        undefined,
        undefined,
        true,
        pageParam,
        pageSize
      );
      if (!response.success) throw new Error(response.error || 'Failed to load');
      return response;
    },
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((acc, p) => acc + p.media.length, 0);
      return loaded < lastPage.total ? allPages.length + 1 : undefined;
    },
  });

  // Sentinel ref for intersection observer
  const sentinelRef = useRef<HTMLDivElement>(null);

  // Infinite scroll using IntersectionObserver on sentinel element
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;

    const scrollContainer = document.querySelector('.main-content');
    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (entry && entry.isIntersecting && hasNextPage && !isFetchingNextPage) {
          fetchNextPage();
        }
      },
      {
        root: scrollContainer,
        rootMargin: '400px',
        threshold: 0,
      }
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  const allItems = useMemo(() => {
    return (data?.pages ?? [])
      .flatMap((p) => p.media)
      .map(toMediaItem)
      .filter((item): item is MediaItem => item !== null);
  }, [data, toMediaItem]);

  const items = useMemo(() => {
    if (typeFilter === 'all') return allItems;
    return allItems.filter((item) => item.type === typeFilter);
  }, [allItems, typeFilter]);

  const total = data?.pages?.[0]?.total ?? 0;

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + ' MB';
    return (bytes / 1073741824).toFixed(1) + ' GB';
  };

  // Close lightbox on escape
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedItem(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div className="gallery" ref={scrollRef}>
      <OperationsHero
        eyebrow="Content"
        title="Media"
        subtitle="Browse downloaded media in a visual grid, filter by site and type, and inspect individual assets in-place."
        badges={[
          { label: 'Visible', value: items.length.toLocaleString(), tone: 'neutral' },
          { label: 'Total', value: total.toLocaleString(), tone: 'info' },
          { label: 'Site', value: site === 'all' ? 'All' : site, tone: 'neutral' },
          { label: 'Type', value: typeFilter, tone: 'neutral' },
        ]}
      />

      {site !== 'all' || typeFilter !== 'all' ? (
        <OperationsNotice tone="info" title="Filtered media view">
          {site !== 'all' ? `Site: ${site}. ` : ''}
          {typeFilter !== 'all' ? `Type: ${typeFilter}. ` : ''}
          Clear the selectors below to return to the full library.
        </OperationsNotice>
      ) : null}

      <header className="gallery-header">
        <div className="gallery-filters">
          <select value={site} onChange={(e) => setSite(e.target.value as typeof site)}>
            <option value="all">All Sites</option>
            <option value="onlyfans">OnlyFans</option>
            <option value="fansly">Fansly</option>
          </select>
          <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value as typeof typeFilter)}>
            <option value="all">All</option>
            <option value="image">Images</option>
            <option value="video">Videos</option>
          </select>
        </div>
      </header>

      {/* Masonry Grid */}
      {isLoading ? (
        <OperationsState
          variant="loading"
          title="Loading media"
          description="Refreshing media rows and visual thumbnails."
        />
      ) : items.length === 0 ? (
        <OperationsState
          title="No media found"
          description="Adjust the current site or type filter to widen the result set."
        />
      ) : (
        <div className="masonry">
          {items.map((item) => (
            <div
              key={item.id}
              className={'masonry-item' + (item.type === 'video' ? ' is-video' : '')}
              onClick={() => setSelectedItem(item)}
            >
              {item.type === 'image' ? (
                <img src={item.url} alt="" loading="lazy" />
              ) : (
                <>
                  <video src={item.url} preload="metadata" muted />
                  <div className="video-badge">▶</div>
                </>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Loading indicator */}
      {isFetchingNextPage && (
        <div className="gallery-loading-more">
          <div className="loading-dots">
            <span></span><span></span><span></span>
          </div>
        </div>
      )}

      {/* Sentinel for infinite scroll - always rendered */}
      <div ref={sentinelRef} className="scroll-sentinel" />

      {/* End marker */}
      {!hasNextPage && items.length > 0 && (
        <div className="gallery-end">✓ All loaded</div>
      )}

      {/* Lightbox */}
      {selectedItem && (
        <div className="lightbox" onClick={() => setSelectedItem(null)}>
          <div className="lightbox-media" onClick={(e) => e.stopPropagation()}>
            {selectedItem.type === 'image' ? (
              <img src={selectedItem.url} alt="" />
            ) : selectedItem.drm && browserSupportsWidevine() ? (
              <LazyVideoPlayer
                drm={{
                  manifestUrl: getDrmManifestUrl(selectedItem.site, selectedItem.numericId),
                  licenseUrl: getDrmLicenseUrl(selectedItem.site, selectedItem.numericId),
                }}
                controls
                autoplay
                fluid={false}
                className="vjs-lightbox"
              />
            ) : selectedItem.drm ? (
              <div className="lightbox-drm-unsupported">
                This browser can't play DRM-protected video. Try Chrome, Edge, or Firefox on desktop.
              </div>
            ) : (
              <LazyVideoPlayer
                src={selectedItem.url}
                controls
                autoplay
                fluid={false}
                className="vjs-lightbox"
              />
            )}
          </div>
          <div className="lightbox-bar">
            <span className="lightbox-name">{selectedItem.filename}</span>
            <span className="lightbox-size">{formatSize(selectedItem.size)}</span>
            <a href={selectedItem.url} download={selectedItem.filename} className="lightbox-dl" onClick={(e) => e.stopPropagation()}>
              ↓ Download
            </a>
          </div>
          <button className="lightbox-x" onClick={() => setSelectedItem(null)}>×</button>
        </div>
      )}
    </div>
  );
}
