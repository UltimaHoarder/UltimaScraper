import type { MPSAnalyzeResponse } from '../../../api/types/mps';

export interface AdaptiveBatchOptions {
  baseBatchSize?: number;
  maxRecommendation?: number;
  includeMissingIds?: boolean;
  routes?: number;
}

export interface AdaptiveBatchRecommendation {
  value: number;
  density: number;
  title: string;
}

export const DEFAULT_BASE_BATCH_SIZE = 5_000;
export const DEFAULT_MAX_RECOMMENDATION = 1_000_000;

/**
 * Calculates an adaptive batch size recommendation scaling inversely with missing-ID density
 * and dynamically with available proxy routes.
 *
 * Formula:
 *   missing_density = missing_count / total_ids
 *   route_multiplier = max(1, routes)
 *   effective_base = base_batch_size * route_multiplier
 *   effective_max = max_recommendation * route_multiplier
 *   adaptive_batch = ceil(effective_base / missing_density)
 *
 * Requirements:
 * - 1 route, 100% missing -> 5,000
 * - 1 route, 50% missing -> 10,000
 * - 1 route, 25% missing -> 20,000
 * - 1 route, 10% missing -> 50,000
 * - 1 route, 1% missing -> 500,000
 * - Scales dynamically with route count (e.g. 10 routes, 50% missing -> 100,000)
 *
 * Edge cases:
 * - When no candidates remain: returns value = 0.
 * - When missing_count is 0 but other sources (invalid, existing) are enabled:
 *   falls back to candidate density (candidate_count / total_ids).
 * - Enforces minimum effective_base and maximum effective_max.
 */
export function calculateAdaptiveBatchSize(
  analysis: MPSAnalyzeResponse | null,
  options?: AdaptiveBatchOptions,
): AdaptiveBatchRecommendation | null {
  if (!analysis) return null;
  const totalIds = analysis.range_size > 0 ? analysis.range_size : analysis.end_id - analysis.start_id + 1;
  if (totalIds <= 0) return null;

  const {
    baseBatchSize = DEFAULT_BASE_BATCH_SIZE,
    maxRecommendation = DEFAULT_MAX_RECOMMENDATION,
    includeMissingIds = true,
    routes = 1,
  } = options ?? {};

  if (analysis.candidate_count <= 0) {
    return {
      value: 0,
      density: 0,
      title: 'No candidates remain in the selected range.',
    };
  }

  let density = 0;
  let densityLabel = 'missing-ID';

  if (includeMissingIds && analysis.missing_count > 0) {
    density = analysis.missing_count / totalIds;
    densityLabel = 'missing-ID';
  } else if (analysis.candidate_count > 0) {
    // Safe fallback for other enabled candidate sources (invalid users or existing profiles)
    density = analysis.candidate_count / totalIds;
    densityLabel = 'candidate';
  }

  if (density <= 0) {
    return {
      value: 0,
      density: 0,
      title: 'No candidates remain in the selected range.',
    };
  }

  const clampedDensity = Math.min(1, Math.max(0, density));
  const routeMultiplier = Math.max(1, routes);
  const effectiveBase = baseBatchSize * routeMultiplier;
  const effectiveMax = maxRecommendation * routeMultiplier;
  const rawBatch = Math.ceil(effectiveBase / clampedDensity);
  const value = Math.max(effectiveBase, Math.min(effectiveMax, rawBatch));

  const densityPercent = clampedDensity * 100;
  const formattedPercent =
    densityPercent < 0.01
      ? densityPercent.toFixed(3)
      : densityPercent < 1
        ? densityPercent.toFixed(2)
        : densityPercent.toFixed(1);

  const routeLabel = routeMultiplier > 1 ? ` × ${routeMultiplier.toLocaleString()} routes` : '';

  return {
    value,
    density: clampedDensity,
    title: `Use adaptive batch size (${formattedPercent}% ${densityLabel} density${routeLabel} = ${value.toLocaleString()} profiles)`,
  };
}
