import { createContext, useContext, type ReactNode } from 'react';

import { CHART_COLORS } from './statisticsActivityModel';

export const StatisticsChartSettingsContext = createContext<{ label: string; settings?: ReactNode } | null>(null);

// Sites, largest archive first. Each site keeps one colour on every chart, and the largest takes the accent.
export const StatisticsSiteOrderContext = createContext<string[]>([]);

export function useSiteColors() {
  const order = useContext(StatisticsSiteOrderContext);
  const rank = (site: string, index: number) => {
    const ranked = order.indexOf(site);
    return ranked === -1 ? order.length + index : ranked;
  };
  return { rank, color: (site: string, index: number) => CHART_COLORS[rank(site, index) % CHART_COLORS.length] };
}
