import { describe, expect, it } from 'vitest';
import type { MPSAnalyzeResponse } from '../../src/api/types/mps';
import {
  calculateAdaptiveBatchSize,
  DEFAULT_BASE_BATCH_SIZE,
  DEFAULT_MAX_RECOMMENDATION,
} from '../../src/features/tools/lib/mpsAdaptiveBatch';

function mockAnalysis(overrides: Partial<MPSAnalyzeResponse> = {}): MPSAnalyzeResponse {
  return {
    site: 'OnlyFans',
    database_min_id: 1,
    database_max_id: 100_000,
    start_id: 1,
    end_id: 100_000,
    range_size: 100_000,
    existing_user_count: 0,
    invalid_user_count: 0,
    invalid_table_ready: true,
    invalid_eligible_count: 0,
    existing_eligible_count: 0,
    missing_count: 50_000,
    candidate_count: 50_000,
    missing_range_count: 100,
    missing_range_count_exact: true,
    missing_ranges_truncated: false,
    missing_ranges: [],
    missing_ids_preview: [],
    candidate_ranges_preview: [],
    candidate_ids_preview: [],
    candidate_preview_truncated: false,
    candidate_offset: 0,
    planned_batch_size: null,
    planned_candidate_count: 50_000,
    remaining_candidate_count: 50_000,
    next_candidate_offset: null,
    has_next_batch: false,
    recommended_batch_size: 10_000,
    batch_recommendations: [],
    warnings: [],
    requires_confirmation: false,
    ...overrides,
  };
}

describe('calculateAdaptiveBatchSize', () => {
  describe('core density scaling requirements', () => {
    it('100% missing -> 5,000', () => {
      const analysis = mockAnalysis({
        range_size: 10_000,
        missing_count: 10_000,
        candidate_count: 10_000,
      });
      const result = calculateAdaptiveBatchSize(analysis);
      expect(result).not.toBeNull();
      expect(result?.value).toBe(5_000);
      expect(result?.density).toBe(1.0);
    });

    it('50% missing -> 10,000', () => {
      const analysis = mockAnalysis({
        range_size: 10_000,
        missing_count: 5_000,
        candidate_count: 5_000,
      });
      const result = calculateAdaptiveBatchSize(analysis);
      expect(result).not.toBeNull();
      expect(result?.value).toBe(10_000);
      expect(result?.density).toBe(0.5);
    });

    it('25% missing -> 20,000', () => {
      const analysis = mockAnalysis({
        range_size: 10_000,
        missing_count: 2_500,
        candidate_count: 2_500,
      });
      const result = calculateAdaptiveBatchSize(analysis);
      expect(result).not.toBeNull();
      expect(result?.value).toBe(20_000);
      expect(result?.density).toBe(0.25);
    });

    it('10% missing -> 50,000', () => {
      const analysis = mockAnalysis({
        range_size: 10_000,
        missing_count: 1_000,
        candidate_count: 1_000,
      });
      const result = calculateAdaptiveBatchSize(analysis);
      expect(result).not.toBeNull();
      expect(result?.value).toBe(50_000);
      expect(result?.density).toBe(0.1);
    });

    it('1% missing -> 500,000', () => {
      const analysis = mockAnalysis({
        range_size: 100_000,
        missing_count: 1_000,
        candidate_count: 1_000,
      });
      const result = calculateAdaptiveBatchSize(analysis);
      expect(result).not.toBeNull();
      expect(result?.value).toBe(500_000);
      expect(result?.density).toBe(0.01);
    });
  });

  describe('monotonic inverse scaling property', () => {
    it('lower missing density always produces an equal or larger recommendation for the same ID space', () => {
      const totalIds = 1_000_000;
      const densities = [1.0, 0.75, 0.5, 0.25, 0.1, 0.05, 0.02, 0.01, 0.005];
      let previousRecommendation = 0;

      for (const d of densities) {
        const count = Math.round(totalIds * d);
        const analysis = mockAnalysis({
          range_size: totalIds,
          missing_count: count,
          candidate_count: count,
        });
        const rec = calculateAdaptiveBatchSize(analysis);
        expect(rec).not.toBeNull();
        expect(rec!.value).toBeGreaterThanOrEqual(previousRecommendation);
        previousRecommendation = rec!.value;
      }
    });
  });

  describe('limits and edge cases', () => {
    it('enforces default maximum recommendation of 1,000,000 for very low missing density', () => {
      const analysis = mockAnalysis({
        range_size: 100_000_000,
        missing_count: 10,
        candidate_count: 10,
      });
      const result = calculateAdaptiveBatchSize(analysis);
      expect(result?.value).toBe(DEFAULT_MAX_RECOMMENDATION);
      expect(result?.value).toBe(1_000_000);
    });

    it('never drops below base_batch_size of 5,000', () => {
      const analysis = mockAnalysis({
        range_size: 10_000,
        missing_count: 10_000,
        candidate_count: 10_000,
      });
      const result = calculateAdaptiveBatchSize(analysis);
      expect(result?.value).toBe(DEFAULT_BASE_BATCH_SIZE);
      expect(result?.value).toBe(5_000);
    });

    it('supports custom base batch size and max recommendation overrides', () => {
      const analysis = mockAnalysis({
        range_size: 10_000,
        missing_count: 5_000,
        candidate_count: 5_000,
      });
      const result = calculateAdaptiveBatchSize(analysis, {
        baseBatchSize: 1_000,
        maxRecommendation: 100_000,
      });
      // 50% density with base 1,000 -> ceil(1,000 / 0.5) = 2,000
      expect(result?.value).toBe(2_000);
    });

    it('returns zero value and appropriate title when candidate count is 0', () => {
      const analysis = mockAnalysis({
        range_size: 10_000,
        missing_count: 0,
        candidate_count: 0,
      });
      const result = calculateAdaptiveBatchSize(analysis);
      expect(result).not.toBeNull();
      expect(result?.value).toBe(0);
      expect(result?.title).toContain('No candidates remain');
    });

    it('returns null when analysis is null or range_size <= 0', () => {
      expect(calculateAdaptiveBatchSize(null)).toBeNull();
      expect(calculateAdaptiveBatchSize(mockAnalysis({ range_size: 0, start_id: 1, end_id: 0 }))).toBeNull();
    });
  });

  describe('source selections and fallbacks', () => {
    it('uses candidate density when missing IDs is 0 but invalid profiles are eligible', () => {
      const analysis = mockAnalysis({
        range_size: 10_000,
        missing_count: 0,
        invalid_eligible_count: 500,
        candidate_count: 500,
      });
      const result = calculateAdaptiveBatchSize(analysis, { includeMissingIds: true });
      expect(result).not.toBeNull();
      // Candidate density = 500 / 10,000 = 0.05 (5%)
      // ceil(5,000 / 0.05) = 100,000
      expect(result?.value).toBe(100_000);
      expect(result?.density).toBe(0.05);
      expect(result?.title).toContain('candidate density');
    });

    it('uses candidate density when user unchecks missing IDs even if missing IDs exist', () => {
      const analysis = mockAnalysis({
        range_size: 100_000,
        missing_count: 80_000,
        existing_eligible_count: 10_000,
        candidate_count: 10_000,
      });
      // User unchecked missing IDs:
      const result = calculateAdaptiveBatchSize(analysis, { includeMissingIds: false });
      expect(result).not.toBeNull();
      // Candidate density = 10,000 / 100,000 = 0.1 (10%)
      // ceil(5,000 / 0.1) = 50,000
      expect(result?.value).toBe(50_000);
      expect(result?.density).toBe(0.1);
    });
  });

  describe('Quick Analyze vs Full Analyze consistency', () => {
    it('produces identical recommendations between quick and full analysis when underlying counts match', () => {
      const quickAnalysis = mockAnalysis({
        range_size: 500_000_000,
        missing_count: 100_000_000, // 20%
        candidate_count: 100_000_000,
        // Quick analysis truncated preview
        candidate_range_count: 1_000,
        candidate_preview_truncated: true,
      });

      const fullAnalysis = mockAnalysis({
        range_size: 500_000_000,
        missing_count: 100_000_000, // 20%
        candidate_count: 100_000_000,
        // Full analysis exact range count
        candidate_range_count: 154_890,
        candidate_preview_truncated: false,
      });

      const quickRec = calculateAdaptiveBatchSize(quickAnalysis);
      const fullRec = calculateAdaptiveBatchSize(fullAnalysis);

      expect(quickRec).not.toBeNull();
      expect(fullRec).not.toBeNull();
      expect(quickRec?.value).toBe(fullRec?.value);
      // Both are 20% density -> 5,000 / 0.2 = 25,000
      expect(quickRec?.value).toBe(25_000);
    });
  });

  describe('dynamic route scaling', () => {
    it('defaults to 1 route when not specified', () => {
      const analysis = mockAnalysis({
        range_size: 10_000,
        missing_count: 5_000,
        candidate_count: 5_000,
      });
      const result = calculateAdaptiveBatchSize(analysis, { routes: 1 });
      const resultDefault = calculateAdaptiveBatchSize(analysis);
      expect(result?.value).toBe(10_000);
      expect(resultDefault?.value).toBe(10_000);
      expect(result?.title).not.toContain('routes');
    });

    it('scales base batch size and recommendation linearly by route count', () => {
      const analysis = mockAnalysis({
        range_size: 10_000,
        missing_count: 5_000,
        candidate_count: 5_000,
      });
      // 50% density with 10 routes -> ceil((5,000 * 10) / 0.5) = 100,000
      const result = calculateAdaptiveBatchSize(analysis, { routes: 10 });
      expect(result?.value).toBe(100_000);
      expect(result?.title).toContain('× 10 routes');
    });

    it('accurately scales large fleets (e.g. 107 routes at 31% missing density)', () => {
      const analysis = mockAnalysis({
        range_size: 598_973_341,
        missing_count: 185_798_165,
        candidate_count: 185_798_165,
      });
      // 185,798,165 / 598,973,341 = 0.31019438...
      // ceil((5,000 * 107) / 0.31019438) = 1,724,725
      const result = calculateAdaptiveBatchSize(analysis, { routes: 107 });
      expect(result?.value).toBe(1_724_725);
      expect(result?.title).toContain('31.0% missing-ID density × 107 routes = 1,724,725 profiles');
    });

    it('scales maximum recommendation cap dynamically with routes', () => {
      const analysis = mockAnalysis({
        range_size: 100_000_000,
        missing_count: 10,
        candidate_count: 10,
      });
      // Default max is 1,000,000 for 1 route; with 5 routes it is 5,000,000
      const result = calculateAdaptiveBatchSize(analysis, { routes: 5 });
      expect(result?.value).toBe(5_000_000);
    });
  });
});
