import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { StatisticsPage } from '../../src/themes/ultima-atlas/views/statistics/StatisticsPage';
import { makeSiteStatistics, makeStatisticsSnapshot } from '../fixtures/statistics';
import { renderWithProviders } from './testUtils';

const api = vi.hoisted(() => ({ getAllStatistics: vi.fn(), getStatisticsHistory: vi.fn(), getStatisticsActivity: vi.fn(), getStatisticsSeasonality: vi.fn() }));
vi.mock('../../src/api/statistics', () => api);

beforeEach(() => {
  api.getStatisticsSeasonality.mockResolvedValue({ metric: 'posts', cycle: 'weekday', exposures: Array(7).fill(52), sites: [] });
  api.getStatisticsActivity.mockResolvedValue({ metric: 'accounts', interval: 'day', range: '30d', date_field: 'join_date', start_at: '2026-10-10T00:00:00Z', end_at: '2026-10-12T00:00:00Z', calculated_at: '2026-10-11T09:00:00Z', sites: [] });
  api.getAllStatistics.mockResolvedValue([
    makeSiteStatistics(), makeSiteStatistics(makeStatisticsSnapshot({ site: 'fansly', total_media_count: 300, downloaded_media_count: 150 })),
  ]);
  api.getStatisticsHistory.mockResolvedValue({ range: '30d', start_date: '2026-10-09', end_date: '2026-10-11', sites: [
    { site: 'onlyfans', available: true, availability_error: null, points: [
      makeStatisticsSnapshot({ bucket_date: '2026-10-09', total_media_count: 80 }),
      makeStatisticsSnapshot({ bucket_date: '2026-10-10', total_media_count: 90 }), makeStatisticsSnapshot(),
    ] },
    { site: 'fansly', available: true, availability_error: null, points: [
      makeStatisticsSnapshot({ site: 'fansly', bucket_date: '2026-10-09', total_media_count: 250 }),
      makeStatisticsSnapshot({ site: 'fansly', bucket_date: '2026-10-10', total_media_count: 270 }),
      makeStatisticsSnapshot({ site: 'fansly', total_media_count: 300 }),
    ] },
  ] });
});

describe('StatisticsPage', () => {
  it('renders archive breakdowns and scopes every summary and history from site interactions', async () => {
    renderWithProviders(<StatisticsPage />);
    expect(screen.queryByRole('region', { name: 'Statistics filters' })).not.toBeInTheDocument();
    await waitFor(() => expect(api.getStatisticsHistory).toHaveBeenCalledWith('all'));
    await screen.findByRole('heading', { name: 'Media composition' });
    expect(screen.getByRole('heading', { name: 'Users vs performers' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Active vs inactive users' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Content types' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Source size profile' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'User role distribution' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'User activity distribution' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Content type distribution' })).toBeInTheDocument();
    await screen.findByRole('img', { name: 'Daily net change bars' });
    const mediaKpi = screen.getByText('Media records', { selector: '.statistics-kpi__label' }).closest('article')!;
    expect(within(mediaKpi).getByText('400')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Download coverage' })).toHaveTextContent('56.3%');
    fireEvent.click(screen.getByRole('button', { name: 'Onlyfans' }));
    expect(within(mediaKpi).getByText('100')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Download coverage' })).toHaveTextContent('75.0%');
    expect(screen.getByRole('region', { name: 'Daily net change' })).toHaveTextContent('+20');
  });

  it('lets site comparison bars focus the page and site cards clear that focus', async () => {
    renderWithProviders(<StatisticsPage />);
    fireEvent.click(await screen.findByRole('button', { name: 'Focus Fansly' }));
    const fanslyBtn = screen.getByRole('button', { name: 'Fansly' });
    expect(fanslyBtn).toHaveAttribute('aria-pressed', 'true');
    const cards = screen.getByRole('heading', { name: 'Archive by site' }).closest('section')!;
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    fireEvent.click(within(cards).getByRole('button', { name: 'Fansly' }));
    expect(fanslyBtn).toHaveAttribute('aria-pressed', 'false');
  });

  it('shows legacy download counts as unavailable while retaining known composition', async () => {
    api.getAllStatistics.mockResolvedValue([makeSiteStatistics(makeStatisticsSnapshot({ downloaded_media_count: null }))]);
    renderWithProviders(<StatisticsPage />);
    const downloads = await screen.findByRole('region', { name: 'Download coverage' });
    expect(downloads).toHaveTextContent('Download count unavailable');
    expect(downloads).toHaveTextContent('Download status unavailable');
    expect(screen.getByRole('img', { name: 'Media type distribution' })).toBeInTheDocument();
    expect(within(downloads).queryByText('0.0%')).not.toBeInTheDocument();
  });

  it('fetches history again when an asynchronous snapshot finishes building', async () => {
    const building = makeSiteStatistics(makeStatisticsSnapshot(), { is_building: true });
    api.getAllStatistics.mockResolvedValue([building]);
    const { queryClient } = renderWithProviders(<StatisticsPage />);
    await screen.findByRole('img', { name: 'Daily net change bars' });
    const previousCalls = api.getStatisticsHistory.mock.calls.length;
    queryClient.setQueryData(['daily-statistics'], [makeSiteStatistics(makeStatisticsSnapshot({ calculated_at: '2026-10-11T10:00:00Z' }))]);
    await waitFor(() => expect(api.getStatisticsHistory.mock.calls.length).toBeGreaterThan(previousCalls));
  });
});
