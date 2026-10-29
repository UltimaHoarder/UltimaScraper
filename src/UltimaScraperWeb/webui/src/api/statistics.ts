import { createHttpClient } from './http';
import type {
  SiteStatistics,
  StatisticsHistoryRange,
  StatisticsHistoryResponse,
  StatisticsActivityMetric,
  StatisticsActivityInterval,
  StatisticsActivityRange,
  StatisticsAccountDate,
  StatisticsActivityResponse,
} from './types/statistics';

const http = createHttpClient();

export async function getAllStatistics(refresh = false): Promise<SiteStatistics[]> {
  const response = await http.get<SiteStatistics[]>('/api/v1/statistics', {
    params: { refresh },
  });
  return response.data;
}

export async function getStatisticsActivity(
  metric: StatisticsActivityMetric,
  interval: StatisticsActivityInterval,
  range: StatisticsActivityRange,
  accountDate: StatisticsAccountDate = 'join_date',
  site?: string,
  refresh = false,
  dates?: { start: string; end: string },
  bucketOffset?: number,
): Promise<StatisticsActivityResponse> {
  const response = await http.get<StatisticsActivityResponse>('/api/v1/statistics/activity', {
    params: { metric, interval, range, account_date: accountDate, refresh, ...(dates ? { start_date: dates.start, end_date: dates.end } : {}), ...(site ? { site } : {}), ...(bucketOffset !== undefined ? { bucket_offset: bucketOffset } : {}) },
  });
  return response.data;
}

export async function getStatisticsHistory(
  range: StatisticsHistoryRange = 'all',
  site?: string
): Promise<StatisticsHistoryResponse> {
  const response = await http.get<StatisticsHistoryResponse>(
    '/api/v1/statistics/history',
    { params: { range, ...(site ? { site } : {}) } }
  );
  return response.data;
}

export async function getStatisticsSeasonality(
  metric: StatisticsActivityMetric, cycle: import('./types/statistics').SeasonalityCycle,
  accountDate: StatisticsAccountDate, site?: string, dates?: { start: string; end: string },
): Promise<import('./types/statistics').StatisticsSeasonalityResponse> {
  const response = await http.get<import('./types/statistics').StatisticsSeasonalityResponse>('/api/v1/statistics/seasonality', {
    params: { metric, cycle, account_date: accountDate, ...(site ? { site } : {}), ...(dates ? { start_date: dates.start, end_date: dates.end } : {}) },
  });
  return response.data;
}
