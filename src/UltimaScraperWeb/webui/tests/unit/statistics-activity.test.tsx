import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { StatisticsActivityChart } from '../../src/themes/ultima-atlas/views/statistics/StatisticsActivityChart';
import { analyzeActivity, advanceActivityBucket, buildActivityBuckets } from '../../src/themes/ultima-atlas/views/statistics/statisticsActivityModel';
import { makeStatisticsActivity } from '../fixtures/statistics';
import { renderWithProviders } from './testUtils';

const api = vi.hoisted(() => ({ getStatisticsActivity: vi.fn() }));
vi.mock('../../src/api/statistics', () => api);

beforeEach(() => { api.getStatisticsActivity.mockImplementation((metric, interval, range) => Promise.resolve(makeStatisticsActivity({ metric, interval, range, ...(interval === 'hour' || interval === 'minute' ? { start_at: '2026-10-11T00:00:00Z', end_at: '2026-10-11T03:00:00Z', calculated_at: '2026-10-11T02:30:00Z' } : {}) }))); });

describe('timestamp activity buckets', () => {
  it('fills confirmed zero periods and excludes the unfinished period from the average', () => {
    const activity = buildActivityBuckets(makeStatisticsActivity());
    expect(activity.buckets.map((bucket) => bucket.count)).toEqual([2, 0, 4]);
    expect(activity.buckets.map((bucket) => bucket.partial)).toEqual([false, false, true]);
    expect(activity).toMatchObject({ total: 6, average: 1, peak: 4, undated: 12 });
  });

  it('keeps unavailable site data unknown and labels partial totals', () => {
    const unavailable = { site: 'fansly', available: false, availability_error: 'offline', undated_count: null, points: [] };
    const data = makeStatisticsActivity();
    const partial = buildActivityBuckets({ ...data, sites: [...data.sites, unavailable] });
    expect(partial).toMatchObject({ total: 6, partialSites: true });
    const unknown = buildActivityBuckets({ ...data, sites: [unavailable] });
    expect(unknown.total).toBeNull();
    expect(unknown.average).toBeNull();
    expect(unknown.buckets.every((bucket) => bucket.count === null)).toBe(true);
  });

  it('uses calendar months and years across leap days', () => {
    expect(advanceActivityBucket(Date.parse('2024-02-01T00:00:00Z'), 'month')).toBe(Date.parse('2024-03-01T00:00:00Z'));
    expect(advanceActivityBucket(Date.parse('2024-01-01T00:00:00Z'), 'year')).toBe(Date.parse('2025-01-01T00:00:00Z'));
  });
});

describe('StatisticsActivityChart', () => {
  it('defaults to start-to-now and keeps account creation on join_date across grouping changes', async () => {
    renderWithProviders(<StatisticsActivityChart metric="accounts" siteScope="onlyfans" />);
    const chart = screen.getByRole('region', { name: 'Account creation' });
    await screen.findByRole('img', { name: 'Accounts per month bar graph' });
    expect(within(chart).queryByRole('combobox', { name: 'Group accounts by' })).not.toBeInTheDocument();
    fireEvent.click(within(chart).getByRole('button', { name: 'Account creation settings' }));
    await waitFor(() => expect(within(chart).getByRole('combobox', { name: 'Accounts time range' })).not.toBeDisabled());
    expect(within(chart).getByRole('combobox', { name: 'Accounts time range' })).toHaveValue('all');
    expect(within(chart).queryByRole('combobox', { name: 'Account date' })).not.toBeInTheDocument();
    expect(api.getStatisticsActivity).toHaveBeenCalledWith('accounts', 'month', 'all', 'join_date', 'onlyfans');
    expect(chart).toHaveTextContent('12 accounts');
    expect(chart).toHaveTextContent('Partial bucket');
    fireEvent.change(within(chart).getByRole('combobox', { name: 'Group accounts by' }), { target: { value: 'day' } });
    await waitFor(() => expect(api.getStatisticsActivity).toHaveBeenCalledWith('accounts', 'day', 'all', 'join_date', 'onlyfans'));
    fireEvent.change(within(chart).getByRole('combobox', { name: 'Group accounts by' }), { target: { value: 'year' } });
    await waitFor(() => expect(api.getStatisticsActivity).toHaveBeenCalledWith('accounts', 'year', 'all', 'join_date', 'onlyfans'));

  });

  it('supports post minute/hour/day graphs, keyboard inspection, and forced refresh', async () => {
    renderWithProviders(<StatisticsActivityChart metric="posts" siteScope="all" />);
    await screen.findByRole('img', { name: 'Posts per month bar graph' });
    fireEvent.click(screen.getByRole('button', { name: 'Post publication settings' }));
    fireEvent.change(screen.getByRole('combobox', { name: 'Group posts by' }), { target: { value: 'hour' } });
    const chart = await screen.findByRole('img', { name: 'Posts per hour bar graph' });
    await waitFor(() => expect(document.querySelector('.statistics-three__readout')).toHaveTextContent('11 Oct, 02:00 UTC'));
    fireEvent.keyDown(chart, { key: 'ArrowLeft' });
    expect(document.querySelector('.statistics-three__readout')).toHaveTextContent('11 Oct, 01:00 UTC');
    fireEvent.change(screen.getByRole('combobox', { name: 'Group posts by' }), { target: { value: 'minute' } });
    await waitFor(() => expect(api.getStatisticsActivity).toHaveBeenCalledWith('posts', 'minute', 'all', 'join_date', undefined));
    fireEvent.change(screen.getByRole('combobox', { name: 'Group posts by' }), { target: { value: 'day' } });
    await waitFor(() => expect(api.getStatisticsActivity).toHaveBeenCalledWith('posts', 'day', 'all', 'join_date', undefined));
    await screen.findByRole('img', { name: 'Posts per day bar graph' });
    fireEvent.click(screen.getByRole('button', { name: 'Refresh posts' }));
    await waitFor(() => expect(api.getStatisticsActivity).toHaveBeenCalledWith('posts', 'day', 'all', 'join_date', undefined, true));
  });

  it('shows source failure without displaying a fake zero series', async () => {
    api.getStatisticsActivity.mockRejectedValue(new Error('offline'));
    renderWithProviders(<StatisticsActivityChart metric="posts" siteScope="all" />);
    await screen.findByRole('alert');
    expect(screen.getByRole('button', { name: 'Post publication settings' })).toBeInTheDocument();
    expect(screen.queryByText('0 posts')).not.toBeInTheDocument();
  });
});

describe('growth rate analysis', () => {
  it('compares equal completed windows without letting a partial bucket create a slowdown', () => {
    const result = analyzeActivity([10, 10, 10, 20, 20, 20, null], 3);
    expect(result).toMatchObject({ previous: 10, recent: 20, change: 1, n: 3, signal: 'Accelerating' });
    expect(result.rolling.at(-1)).toBeNull();
    expect(result.rolling.slice(0, 2)).toEqual([null, null]);
    expect(analyzeActivity([0, 0, 0, 2, 2, 2], 3).change).toBeNull();
  });
  it('fits exponential rates and refuses zero counts instead of taking invalid logarithms', () => {
    const result = analyzeActivity([2, 4, 8, 16, 32, 64]);
    expect(result.exponential!.rate).toBeCloseTo(1);
    expect(result.exponential!.r2).toBeCloseTo(1);
    expect(analyzeActivity([0, 4, 8, 16, 32, 64]).exponential).toBeNull();
    expect(analyzeActivity([1, 2]).linear).toBeNull();
  });
});

it('keeps hourly custom dates, full totals, and cumulative counts while navigating history', async () => {
  renderWithProviders(<StatisticsActivityChart metric="posts" siteScope="all" />);
  await screen.findByRole('img', { name: 'Posts per month bar graph' });
  fireEvent.click(screen.getByRole('button', { name: 'Post publication settings' }));
  fireEvent.change(screen.getByRole('combobox', { name: 'Group posts by' }), { target: { value: 'hour' } });
  await screen.findByRole('img', { name: 'Posts per hour bar graph' });
  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Posts time range' })).not.toBeDisabled());
  expect(screen.getByRole('combobox', { name: 'Posts time range' })).toHaveValue('all');
  fireEvent.change(screen.getByRole('combobox', { name: 'Posts time range' }), { target: { value: 'custom' } });
  fireEvent.change(screen.getByLabelText('Posts from'), { target: { value: '2020-01-15' } });
  fireEvent.change(screen.getByLabelText('Posts through'), { target: { value: '2026-10-10' } });
  api.getStatisticsActivity.mockResolvedValue(makeStatisticsActivity({ interval: 'hour', range: 'custom', start_at: '2020-01-15T00:00:00Z', end_at: '2026-10-11T00:00:00Z', window_start_at: '2026-10-10T00:00:00Z', window_end_at: '2026-10-10T03:00:00Z', bucket_count: 59000, bucket_offset: 57000, completed_bucket_count: 58999, coverage_end_at: '2026-10-11T00:00:00Z', sites: [{ site: 'onlyfans', available: true, availability_error: null, undated_count: 8, total_count: 100, completed_count: 100, before_window_count: 90, points: [{ bucket_started_at: '2026-10-10T02:00:00Z', count: 10 }] }] }));
  fireEvent.click(screen.getByRole('button', { name: 'Apply dates' }));
  await waitFor(() => expect(api.getStatisticsActivity).toHaveBeenCalledWith('posts', 'hour', 'custom', 'join_date', undefined, false, { start: '2020-01-15', end: '2026-10-10' }));
  expect(screen.queryByRole('slider', { name: 'Pan posts history' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Start' })).not.toBeInTheDocument();
  await screen.findByRole('img', { name: 'Posts per hour bar graph' });
  expect(screen.queryByText(/Showing month buckets/)).not.toBeInTheDocument();
  await waitFor(() => expect(document.querySelector('.statistics-activity__summary')).toHaveTextContent('100'));
  fireEvent.change(screen.getByRole('combobox', { name: 'Posts view' }), { target: { value: 'cumulative' } });
  expect(document.querySelector('.statistics-three__readout')).toHaveTextContent('100');
});

it('renders real dumped accounts month activity without errors', async () => {
  const fs = await import('node:fs');
  const path = fs.existsSync('/tmp/live_backend_accounts_month.json') ? '/tmp/live_backend_accounts_month.json' : '/tmp/real_activity_accounts_month.json';
  if (fs.existsSync(path)) {
    const realData = JSON.parse(fs.readFileSync(path, 'utf-8'));
    api.getStatisticsActivity.mockResolvedValue(realData);
    renderWithProviders(<StatisticsActivityChart metric="accounts" siteScope="all" />);
    await screen.findByRole('img', { name: 'Accounts per month bar graph' });
  }
});


