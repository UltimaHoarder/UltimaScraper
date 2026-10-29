import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StatisticsThreeChart } from '../../src/themes/ultima-atlas/views/statistics/StatisticsThreeChart';

describe('interactive chart controls and accessible data', () => {
  it('labels the selected stacked bar total without adding the trendline', () => {
    const { container } = render(<StatisticsThreeChart labels={['First', 'Second']} stacked series={[
      { label: 'One', color: '#24aac3', values: [20, 2] },
      { label: 'Two', color: '#ffd303', values: [10, 3] },
      { label: 'Trend', color: '#ffffff', values: [100, 100], kind: 'line' },
    ]} label="Stacked bars" />);
    expect(screen.getByLabelText('Selected bar: 5')).toHaveTextContent('5');
    expect(container.querySelector('.statistics-three__cursor')).toHaveStyle({ height: '4.03%' });
    fireEvent.click(screen.getByRole('button', { name: 'Two' }));
    expect(screen.getByLabelText('Selected bar: 2')).toHaveTextContent('2');
  });
  it('steps through exact values, filters series, and pans a zoomed window', async () => {
    const labels = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H'];
    const { container } = render(<StatisticsThreeChart labels={labels} series={[{ label: 'Posts', color: '#24aac3', values: [1, 2, null, 4, 5, 6, 7, 8] }, { label: 'Fit', color: '#ffffff', values: [1, 2, 3, 4, 5, 6, 7, 8], kind: 'line' }]} label="Publishing chart" />);
    expect(screen.queryByText(/Hover or touch/)).not.toBeInTheDocument();
    expect(container.querySelector('.statistics-three__peak-badge')).toHaveTextContent('PEAK');
    expect(container.querySelector('.statistics-three__peak-badge')).toHaveTextContent('8');
    fireEvent.keyDown(screen.getByRole('img', { name: 'Publishing chart' }), { key: 'ArrowLeft' });
    expect(container.querySelector('.statistics-three__readout')).toHaveTextContent('G');
    fireEvent.click(screen.getByRole('button', { name: 'Fit' }));
    expect(screen.getByRole('button', { name: 'Fit' })).toHaveAttribute('aria-pressed', 'false');
    expect(container.querySelector('.statistics-three__readout')).not.toHaveTextContent('Fit');
    expect(screen.queryByRole('button', { name: 'Zoom in Publishing chart' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Zoom out Publishing chart' })).not.toBeInTheDocument();
    const chart = screen.getByRole('img', { name: 'Publishing chart' });
    fireEvent.wheel(chart, { deltaY: -100 });
    const resetBtn = screen.getByRole('button', { name: 'Show all' });
    expect(resetBtn).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.queryByText('View data table')).not.toBeInTheDocument();
    fireEvent.click(resetBtn);
    expect(screen.queryByRole('button', { name: 'Show all' })).not.toBeInTheDocument();
    expect(container.querySelector('.statistics-three__peak-badge')).toHaveTextContent('8');
  });
  it('opens a long bar series on its latest buckets and shows all on request', () => {
    const labels = Array.from({ length: 120 }, (_, i) => `Month ${i + 1}`);
    render(<StatisticsThreeChart labels={labels} series={[{ label: 'Posts', color: '#24aac3', values: labels.map((_, i) => i) }]} label="Long bars" />);
    expect(screen.getByRole('toolbar')).toHaveTextContent('UTC · 36 of 120 points');
    fireEvent.click(screen.getByRole('button', { name: 'Show all' }));
    expect(screen.getByRole('toolbar')).toHaveTextContent('UTC · 120 points');
    expect(screen.queryByRole('button', { name: 'Show all' })).not.toBeInTheDocument();
  });
  it('shows every point of a long line series', () => {
    const labels = Array.from({ length: 120 }, (_, i) => `Day ${i + 1}`);
    render(<StatisticsThreeChart kind="line" labels={labels} series={[{ label: 'Media', color: '#24aac3', values: labels.map((_, i) => i) }]} label="Long line" />);
    expect(screen.getByRole('toolbar')).toHaveTextContent('UTC · 120 points');
  });
});
