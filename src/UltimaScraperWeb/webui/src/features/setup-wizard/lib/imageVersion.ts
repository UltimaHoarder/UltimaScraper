import type { DetectResponse, InstallEnvironment } from '../../../api/webui';

export type ImageSource = 'copy' | 'target' | 'registry';

/** The registry root the release image, ultimascraper, is published under. */
export const DEFAULT_IMAGE_REGISTRY = 'ghcr.io/ultimahoarder/ultimascraper';

/**
 * The version to offer for an image source. A registry has this WebUI's own
 * release; the images already here only exist under their local tags, so
 * a registry install never defaults to one of those.
 */
export function versionForSource(
  source: ImageSource,
  detection: DetectResponse | null,
  environment: InstallEnvironment | null,
): string {
  const recommended = detection?.recommended_version ?? '';
  if (source === 'registry') {
    if (detection?.recommended_image_source === 'registry' && recommended) return recommended;
    return environment?.version || '0.1.0';
  }
  if (detection && detection.recommended_image_source !== 'registry' && recommended) return recommended;
  const local = detection?.facts.local_images.find(
    (release) => release.architecture === detection.facts.architecture,
  );
  return local?.version || recommended || environment?.version || '0.1.0';
}

/**
 * Normalizes a Docker registry prefix.
 * Strips leading http(s):// protocols, trailing slashes, and converts
 * to lowercase to meet Docker / OCI repository naming specifications.
 */
export function normalizeImagePrefix(raw: string): string {
  return raw
    .trim()
    .replace(/^https?:\/\//i, '')
    .replace(/\/+$/, '')
    .toLowerCase();
}

