import { describe, expect, it } from 'vitest';

import type { DetectResponse, InstallEnvironment } from '../../src/api/webui';
import { versionForSource } from '../../src/features/setup-wizard/lib/imageVersion';

const environment = { version: '0.1.0' } as InstallEnvironment;

function detection(source: DetectResponse['recommended_image_source'], version: string): DetectResponse {
  return {
    facts: {
      architecture: 'arm64',
      local_images: [{ version: 'acceptance-arm64', architecture: 'arm64', names: ['backend', 'worker'] }],
    },
    recommended_image_source: source,
    recommended_version: version,
  } as unknown as DetectResponse;
}

describe('versionForSource', () => {
  it('never offers a local-only tag for a registry install', () => {
    const local = detection('target', 'acceptance-arm64');

    expect(versionForSource('registry', local, environment)).toBe('0.1.0');
    expect(versionForSource('target', local, environment)).toBe('acceptance-arm64');
    expect(versionForSource('copy', local, environment)).toBe('acceptance-arm64');
  });

  it('keeps the recommendation when detection itself chose the registry', () => {
    const registry = detection('registry', '0.2.0');

    expect(versionForSource('registry', registry, environment)).toBe('0.2.0');
    // Switching to local images offers the tag those images carry.
    expect(versionForSource('target', registry, environment)).toBe('acceptance-arm64');
  });

  it('falls back to this WebUI release before detection finishes', () => {
    expect(versionForSource('registry', null, environment)).toBe('0.1.0');
    expect(versionForSource('target', null, null)).toBe('0.1.0');
  });
});
