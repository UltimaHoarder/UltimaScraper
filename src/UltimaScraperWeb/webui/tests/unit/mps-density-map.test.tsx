import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MPSIdSpaceMap } from '../../src/features/tools/components/MPSIdSpaceMap';
import type { MPSAnalyzeResponse } from '../../src/api/types/mps';

/** The bar hover tooltip, distinct from the always-present chart help tooltip. */
function barTooltip(): HTMLElement | null {
  return screen.queryAllByRole('tooltip').find((node) => node.id === 'mps-bar-tooltip') ?? null;
}

const densityFixture: MPSAnalyzeResponse = {
  site: 'OnlyFans',
  database_min_id: 1,
  database_max_id: 100_000,
  start_id: 1,
  end_id: 100_000,
  range_size: 100_000,
  existing_user_count: 10_000,
  invalid_user_count: 5_000,
  invalid_table_ready: true,
  invalid_eligible_count: 5_000,
  existing_eligible_count: 0,
  missing_count: 85_000,
  candidate_count: 90_000,
  missing_range_count: 50,
  missing_range_count_exact: true,
  candidate_range_count: 50,
  missing_ranges_truncated: false,
  missing_ranges: [],
  missing_ids_preview: [],
  candidate_ranges_preview: [],
  candidate_ids_preview: [],
  candidate_preview_truncated: false,
  density_resolution: 4,
  density_is_exact: false,
  density_buckets: [
    {
      start_id: 1,
      end_id: 25_000,
      missing_count: 20_000,
      invalid_count: 2_000,
      existing_count: 3_000,
      candidate_count: 22_000,
      is_exact: true,
    },
    {
      start_id: 25_001,
      end_id: 50_000,
      missing_count: 25_000,
      invalid_count: 0,
      existing_count: 0,
      candidate_count: 25_000,
      is_exact: true,
    },
    {
      start_id: 50_001,
      end_id: 75_000,
      missing_count: 20_000,
      invalid_count: 1_500,
      existing_count: 3_500,
      candidate_count: 21_500,
      is_exact: false,
    },
    {
      start_id: 75_001,
      end_id: 100_000,
      missing_count: 20_000,
      invalid_count: 1_500,
      existing_count: 3_500,
      candidate_count: 21_500,
      is_exact: false,
    },
  ],
  dense_pockets: [
    {
      start_id: 1,
      end_id: 50_000,
      candidate_count: 47_000,
      density_percentage: 94.0,
      missing_count: 45_000,
      invalid_count: 2_000,
      existing_count: 3_000,
    },
  ],
  candidate_offset: 0,
  planned_batch_size: 500,
  planned_candidate_count: 500,
  remaining_candidate_count: 90_000,
  next_candidate_offset: 500,
  has_next_batch: true,
  recommended_batch_size: 1_000,
  batch_recommendations: [],
  warnings: [],
  requires_confirmation: false,
};

describe('MPSIdSpaceMap with Density Buckets', () => {
  it('renders backend density buckets with density-mode class and exact count', () => {
    const onSiteChange = vi.fn();

    const { container } = render(
      <MPSIdSpaceMap
        site="OnlyFans"
        onSiteChange={onSiteChange}
        analysis={densityFixture}
        loading={false}
      />,
    );

    const plot = container.querySelector('.mps-id-map-plot');
    expect(plot).toHaveClass('density-mode');

    const bars = container.querySelectorAll('.mps-id-map-bar');
    expect(bars).toHaveLength(4);

    // First two buckets are exact; 3rd and 4th are estimated
    expect(bars[0]).not.toHaveClass('estimated');
    expect(bars[1]).not.toHaveClass('estimated');
    expect(bars[2]).toHaveClass('estimated');
    expect(bars[3]).toHaveClass('estimated');

    // Title should contain exact or estimated label
    expect(bars[0].getAttribute('aria-label')).toContain('Exact');
    expect(bars[2].getAttribute('aria-label')).toContain('Estimated (uninspected span)');

    expect(screen.getByText('Profiles per ID interval (stacked)')).toBeInTheDocument();
    expect(screen.getByText('Provider profile ID')).toBeInTheDocument();
    expect(screen.getByLabelText('Profile count scale')).toHaveTextContent('25K');

    // Legend should indicate estimated status
    expect(screen.getByText('Estimated')).toBeInTheDocument();
  });

  it('combines 512 API buckets into 72 separated display columns without losing counts', () => {
    const buckets = Array.from({ length: 512 }, (_, index) => ({
      start_id: index * 100 + 1, end_id: (index + 1) * 100,
      missing_count: 60, invalid_count: 10, existing_count: 30,
      candidate_count: 70, is_exact: index < 256,
    }));
    const { container } = render(<MPSIdSpaceMap site="OnlyFans" onSiteChange={vi.fn()}
      analysis={{ ...densityFixture, end_id: 51200, density_buckets: buckets }}
      loading={false} />);
    const bars = [...container.querySelectorAll('.mps-id-map-bar')];
    expect(bars).toHaveLength(72);
    expect(bars[0].getAttribute('aria-label')).toContain('1 – 711');
    expect(bars.at(-1)?.getAttribute('aria-label')).toContain('50,489 – 51,200');
    expect(bars.at(-1)).toHaveClass('estimated');
    // Uniform classification totals stay uniform regardless of selected candidates.
    const heights = bars.map((bar) => (bar.querySelector('i') as HTMLElement).style.height);
    expect(heights.every((height) => Math.abs(parseFloat(height) - 100) < 0.2)).toBe(true);
  });

  it('stacks each interval with its largest category on top', () => {
    const { container } = render(<MPSIdSpaceMap site="OnlyFans" onSiteChange={vi.fn()}
      analysis={densityFixture} loading={false}
      sources={{ missing: true, invalid: false, existing: false }} />);
    const bars = [...container.querySelectorAll('.mps-id-map-bar')];
    expect(bars.every((bar) => (bar.querySelector('i') as HTMLElement).style.height === '100%')).toBe(true);
    expect(bars[0].querySelector('.seg-missing')).toHaveStyle({height: '80%'});
    expect(bars[0].querySelector('.seg-existing')).toHaveClass('off');
    expect(bars[0].querySelector('.seg-existing')).toHaveStyle({height: '12%'});
    expect(bars[0].querySelector('.seg-invalid')).toHaveStyle({height: '8%'});
    // Column-reverse draws the last child at the top of the stack.
    expect(bars[0].querySelector('i')?.lastElementChild).toHaveClass('seg-missing');
    expect(bars[0].querySelector('i')?.firstElementChild).toHaveClass('seg-invalid');
  });

  it('falls back to 72 synthesized buckets when density_buckets is absent', () => {
    const onSiteChange = vi.fn();
    const fallbackFixture: MPSAnalyzeResponse = {
      ...densityFixture,
      density_buckets: undefined,
      candidate_ranges_preview: [{ start_id: 1, end_id: 100, count: 100 }],
    };

    const { container } = render(
      <MPSIdSpaceMap
        site="OnlyFans"
        onSiteChange={onSiteChange}
        analysis={fallbackFixture}
        loading={false}
      />,
    );

    const plot = container.querySelector('.mps-id-map-plot');
    expect(plot).not.toHaveClass('density-mode');

    const bars = container.querySelectorAll('.mps-id-map-bar');
    expect(bars).toHaveLength(72);
  });

  it('does not present an estimated zero as a confirmed absence', () => {
    const buckets = densityFixture.density_buckets!.map((bucket, index) => index === 2 ? {...bucket, invalid_count: 0} : bucket);
    const { container } = render(<MPSIdSpaceMap site="OnlyFans" onSiteChange={vi.fn()}
      analysis={{...densityFixture, density_buckets: buckets}} loading={false} />);
    fireEvent.pointerEnter(container.querySelectorAll('.mps-id-map-bar')[2]);
    expect(within(barTooltip()!).getByText('Not resolved')).toBeInTheDocument();
    fireEvent.pointerEnter(container.querySelectorAll('.mps-id-map-bar')[1]);
    expect(within(barTooltip()!).queryByText('Not resolved')).not.toBeInTheDocument();
    expect(within(barTooltip()!).getAllByText('0')).toHaveLength(2);
  });

  it('shows colour-separated counts on hover without range selection controls', () => {
    const { container } = render(<MPSIdSpaceMap site="OnlyFans" onSiteChange={vi.fn()}
      analysis={densityFixture} loading={false} sources={{missing: true, invalid: false, existing: false}} />);
    const missing = screen.getAllByRole('img', {name: /^Missing: 20,000 profiles/})[0];
    fireEvent.pointerEnter(missing);
    const tooltip = barTooltip()!;
    expect(within(tooltip).getByText('20,000')).toBeInTheDocument();
    expect(within(tooltip).getByText('2,000')).toBeInTheDocument();
    expect(within(tooltip).getByText('3,000')).toBeInTheDocument();
    expect(within(tooltip).getByText('Invalid (excluded)')).toBeInTheDocument();
    expect(within(tooltip).getByText('Missing').closest('.mps-id-map-tooltip-row')).toHaveClass('active');
    fireEvent.focus(screen.getByRole('img', {name: 'Existing: 3,000 profiles'}));
    expect(within(barTooltip()!).getByText('Existing (excluded)').closest('.mps-id-map-tooltip-row')).toHaveClass('active');
    fireEvent.pointerLeave(container.querySelector('.mps-id-map-plot')!);
    expect(barTooltip()).toBeNull();
    expect(screen.queryByRole('button', {name: 'Zoom to selection'})).not.toBeInTheDocument();
    expect(screen.queryByRole('button', {name: 'Full range'})).not.toBeInTheDocument();
    expect(container.querySelector('.mps-id-map-brush')).toBeNull();
  });
});
