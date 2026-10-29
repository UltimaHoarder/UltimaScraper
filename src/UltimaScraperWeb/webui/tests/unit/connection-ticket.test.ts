import { describe, expect, it } from 'vitest';
import { parseTicketString } from '../../src/features/connections/lib/ticket';

describe('parseTicketString', () => {
  it('parses a usr://ticket/ base64 ticket', () => {
    const payload = {
      v: 1,
      name: 'nas-backend',
      base_url: 'http://192.168.50.60:21121',
      token: 'secret123',
      tls_verify: false,
      cluster_id: 'cluster-abc',
    };
    const b64 = btoa(JSON.stringify(payload)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    const ticket = `usr://ticket/${b64}`;

    const parsed = parseTicketString(ticket);
    expect(parsed).toEqual({
      name: 'nas-backend',
      base_url: 'http://192.168.50.60:21121',
      token: 'secret123',
      tls_verify: false,
      cluster_id: 'cluster-abc',
    });
  });

  it('parses a usr_ticket_ prefixed ticket', () => {
    const payload = {
      name: 'worker-1',
      base_url: 'https://backend.local:21121/',
      token: 'my-token',
    };
    const b64 = btoa(JSON.stringify(payload));
    const ticket = `usr_ticket_${b64}`;

    const parsed = parseTicketString(ticket);
    expect(parsed).toEqual({
      name: 'worker-1',
      base_url: 'https://backend.local:21121',
      token: 'my-token',
      tls_verify: true,
      cluster_id: undefined,
    });
  });

  it('parses a standard usr:// URI', () => {
    const uri = 'usr://admin_pass@nas.local:21121?name=My+NAS&tls=1';
    const parsed = parseTicketString(uri);
    expect(parsed).toEqual({
      name: 'My NAS',
      base_url: 'https://nas.local:21121',
      token: 'admin_pass',
      tls_verify: true,
      cluster_id: undefined,
    });
  });

  it('returns null on invalid ticket', () => {
    expect(parseTicketString('')).toBeNull();
    expect(parseTicketString('not-a-ticket')).toBeNull();
    expect(parseTicketString('usr://ticket/!!!invalid-base64')).toBeNull();
  });
});
