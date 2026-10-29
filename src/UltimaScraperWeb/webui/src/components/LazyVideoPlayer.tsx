import { lazy, Suspense } from 'react';
import type { VideoPlayerProps } from './VideoPlayer';

// video.js and its streaming/DRM plugins are large; load them only when a
// video is actually rendered instead of in the application entry chunk.
const VideoPlayer = lazy(async () => ({ default: (await import('./VideoPlayer')).VideoPlayer }));

export function LazyVideoPlayer(props: VideoPlayerProps) {
  return (
    <Suspense fallback={null}>
      <VideoPlayer {...props} />
    </Suspense>
  );
}
