export interface TimedChartPoint {
  timestamp: number;
  value: number;
}

function clamp(value: number, minimum = 0, maximum = 100): number {
  return Math.min(maximum, Math.max(minimum, value));
}

export function chartPath(
  points: TimedChartPoint[],
  width = 640,
  height = 180,
  scaleMaximum?: number,
  domainStart = points[0]?.timestamp ?? 0,
  domainEnd = points.at(-1)?.timestamp ?? domainStart + 1,
  scaleMinimum = 0,
): string {
  const minimum = Number.isFinite(scaleMinimum) ? scaleMinimum : 0;
  const maximum = Math.max(
    scaleMaximum ?? Math.max(...points.map((point) => point.value), 0),
    minimum + 1,
  );
  const scaleSpan = maximum - minimum;
  const topPadding = 12;
  const usableHeight = height - topPadding * 2;
  const baseline = height - topPadding;
  if (points.length === 0) return `M0 ${baseline} L${width} ${baseline}`;

  const start = Number.isFinite(domainStart) ? domainStart : points[0].timestamp;
  const end = Number.isFinite(domainEnd) ? Math.max(domainEnd, start + 1) : start + 1;
  const span = end - start;
  const pointPath = points
    .slice()
    .sort((left, right) => left.timestamp - right.timestamp)
    .map((point, index) => {
      const x = Math.min(width, Math.max(0, ((point.timestamp - start) / span) * width));
      const y = height - topPadding - (clamp((point.value - minimum) / scaleSpan, 0, 1) * usableHeight);
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(' ');

  // A single observation still needs a visible mark in the SVG stroke.
  if (points.length === 1) {
    const point = points[0];
    const x = Math.min(width, Math.max(0, ((point.timestamp - start) / span) * width));
    const y = height - topPadding - (clamp((point.value - minimum) / scaleSpan, 0, 1) * usableHeight);
    return `M${Math.max(0, x - 1).toFixed(1)} ${y.toFixed(1)} L${Math.min(width, x + 1).toFixed(1)} ${y.toFixed(1)}`;
  }
  return pointPath;
}
