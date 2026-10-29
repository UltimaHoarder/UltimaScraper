import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getMediaFileUrl } from '../api/media';
import { VideoPlayer } from '../components/VideoPlayer';

export function VideoPage() {
  const navigate = useNavigate();
  const { site, mediaId } = useParams<{ site: string; mediaId: string }>();
  const [error, setError] = useState(false);
  const decodedSite = decodeURIComponent(site ?? '');
  const parsedMediaId = Number(mediaId);
  const validMedia = decodedSite.length > 0 && Number.isInteger(parsedMediaId) && parsedMediaId > 0;
  const streamUrl = validMedia ? getMediaFileUrl(decodedSite, parsedMediaId) : '';

  return (
    <main className="video-page" data-testid="video-page">
      <div className="video-page-header">
        <button type="button" className="video-page-back" onClick={() => navigate(-1)}>
          ← Back
        </button>
        <div>
          <h1>Video</h1>
          {validMedia && <p>{decodedSite} · media {parsedMediaId}</p>}
        </div>
      </div>

      <section className="video-page-player" aria-label="Video player">
        {!validMedia ? (
          <p className="video-page-message">This video link is invalid.</p>
        ) : error ? (
          <div className="video-page-message">
            <h2>Video could not be loaded</h2>
            <p>Check the API response for this media item, then try again.</p>
            <button type="button" onClick={() => { setError(false); window.location.reload(); }}>
              Try again
            </button>
          </div>
        ) : (
          <VideoPlayer
            src={streamUrl}
            type="video/mp4"
            controls
            autoplay
            fluid={false}
            responsive
            className="video-page-video"
            onError={() => setError(true)}
          />
        )}
      </section>
    </main>
  );
}
