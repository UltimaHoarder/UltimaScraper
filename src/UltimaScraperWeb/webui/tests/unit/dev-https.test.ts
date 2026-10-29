import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { resolveDevHttps } from '../../config/devHttps';

describe('dev server HTTPS', () => {
  it('serves HTTP unless main.py passes a certificate', () => {
    expect(resolveDevHttps({})).toBeUndefined();
  });

  it('reads the certificate and key it is given', () => {
    const directory = mkdtempSync(join(tmpdir(), 'usr-dev-https-'));
    writeFileSync(join(directory, 'cert.pem'), 'CERT');
    writeFileSync(join(directory, 'key.pem'), 'KEY');

    const https = resolveDevHttps({
      USR_WEBUI_TLS_CERT_FILE: join(directory, 'cert.pem'),
      USR_WEBUI_TLS_KEY_FILE: join(directory, 'key.pem'),
    });

    expect(https?.cert.toString()).toBe('CERT');
    expect(https?.key.toString()).toBe('KEY');
    expect(() => resolveDevHttps({ USR_WEBUI_TLS_CERT_FILE: join(directory, 'cert.pem') })).toThrow(/both/);
  });
});
