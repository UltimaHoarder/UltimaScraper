import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { reportServedBy } from '../../src/api/failover';
import { createHttpClient } from '../../src/api/http';
import { FailoverNotice } from '../../src/features/connections/FailoverNotice';

afterEach(() => {
  reportServedBy(null);
  window.history.replaceState(null, '', '/');
});

describe('FailoverNotice', () => {
  it('says which cluster member answers while the open backend is down', async () => {
    window.history.replaceState(null, '', '/b/nas/jobs');
    const client = createHttpClient();
    let servedBy: string | undefined = 'nas2';
    client.defaults.adapter = async (config) => ({
      data: {}, status: 200, statusText: 'OK', headers: servedBy ? { 'x-usr-served-by': servedBy } : {}, config,
    });
    render(<FailoverNotice />);
    expect(screen.queryByRole('status')).toBeNull();

    await act(async () => {
      await client.get('/api/v1/jobs');
    });
    expect(screen.getByRole('status')).toHaveTextContent('nas unreachable · reading from nas2');

    // The open backend answers again.
    servedBy = undefined;
    await act(async () => {
      await client.get('/api/v1/jobs');
    });
    expect(screen.queryByRole('status')).toBeNull();
  });
});
