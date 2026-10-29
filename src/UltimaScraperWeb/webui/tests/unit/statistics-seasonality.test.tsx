import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { StatisticsSeasonality } from '../../src/themes/ultima-atlas/views/statistics/StatisticsSeasonality';
import { renderWithProviders } from './testUtils';
const api = vi.hoisted(() => ({ getStatisticsSeasonality: vi.fn() }));
vi.mock('../../src/api/statistics', () => api);
beforeEach(() => api.getStatisticsSeasonality.mockResolvedValue({ metric: 'posts', cycle: 'weekday', date_field: 'created_at', start_date: '2024-01-01', end_date: '2024-01-14', calculated_at: '2024-01-15T00:00:00Z', exposures: [2, 2, 2, 2, 2, 2, 2], sites: [{ site: 'onlyfans', available: true, counts: [2, 4, 6, 8, 10, 12, 14] }, { site: 'fansly', available: false, counts: [], availability_error: 'offline' }] }));
describe('seasonality normalization and controls', () => {
  it('normalizes completed observations and keeps unavailable sites out of the profile', async () => {
    renderWithProviders(<StatisticsSeasonality siteScope="all" />);
    await screen.findByRole('img', { name: 'Seasonality bar graph' });
    fireEvent.click(screen.getByRole('button', { name: 'Seasonality settings' }));
    await waitFor(() => expect(screen.getByRole('combobox', { name: 'Seasonality range' })).not.toBeDisabled());
    expect(screen.getByRole('combobox', { name: 'Seasonality range' })).toHaveValue('all');
    expect(document.querySelector('.statistics-three__readout')).toHaveTextContent('Onlyfans 7');
    expect(document.querySelector('.statistics-three__readout')).not.toHaveTextContent('Fansly');
    expect(screen.queryByText(/Some sites are unavailable/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox', { name: 'Seasonality values' }), { target: { value: 'total' } });
    expect(document.querySelector('.statistics-three__readout')).toHaveTextContent('Onlyfans 14');
    fireEvent.change(screen.getByRole('combobox', { name: 'Seasonality cycle' }), { target: { value: 'hour' } });
    await waitFor(() => expect(api.getStatisticsSeasonality).toHaveBeenCalledWith('posts', 'hour', 'join_date', undefined, undefined));
  });
});

it('uses join_date for account seasonality and pre-fills custom dates from the first record', async () => {
  renderWithProviders(<StatisticsSeasonality siteScope="onlyfans" />);
  await screen.findByRole('img', { name: 'Seasonality bar graph' });
  fireEvent.click(screen.getByRole('button', { name: 'Seasonality settings' }));
  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Seasonality range' })).not.toBeDisabled());
  fireEvent.change(screen.getByRole('combobox', { name: 'Seasonality metric' }), { target: { value: 'accounts' } });
  await waitFor(() => expect(api.getStatisticsSeasonality).toHaveBeenCalledWith('accounts', 'weekday', 'join_date', 'onlyfans', undefined));
  await screen.findByRole('img', { name: 'Seasonality bar graph' });
  expect(screen.queryByRole('combobox', { name: 'Seasonality account date' })).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole('combobox', { name: 'Seasonality range' }), { target: { value: 'custom' } });
  expect(screen.getByLabelText('Seasonality from')).toHaveValue('2024-01-01');
  expect(screen.getByLabelText('Seasonality through')).toHaveValue(new Date().toISOString().slice(0, 10));
});
