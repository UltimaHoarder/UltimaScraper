import type {
  ProxyAnalyzerResult,
} from '../../../api/types/network';

function findBestAnalyzerResult(
  results: ProxyAnalyzerResult[]
): ProxyAnalyzerResult {
  return results.reduce((best, current) => {
    const bestSuccessRate = best.successes / best.requests;
    const currentSuccessRate = current.successes / current.requests;

    if (currentSuccessRate >= 0.95 && current.efficiency_score > best.efficiency_score) {
      return current;
    }

    if (currentSuccessRate >= 0.95 && bestSuccessRate < 0.95) {
      return current;
    }

    return best;
  }, results[0]);
}

export function getGroupedAnalyzerResults(results: ProxyAnalyzerResult[]) {
  const groupedResults = results.reduce<Record<number, ProxyAnalyzerResult[]>>((acc, result) => {
    const currentResults = acc[result.concurrency] ?? [];
    currentResults.push(result);
    acc[result.concurrency] = currentResults;
    return acc;
  }, {});

  return Object.keys(groupedResults)
    .map(Number)
    .sort((left, right) => {
      const bestLeft = findBestAnalyzerResult(groupedResults[left]);
      const bestRight = findBestAnalyzerResult(groupedResults[right]);
      return bestRight.efficiency_score - bestLeft.efficiency_score;
    })
    .map((concurrency) => ({
      concurrency,
      results: groupedResults[concurrency],
      bestResult: findBestAnalyzerResult(groupedResults[concurrency]),
    }));
}

export function getErrorCount(counts: Record<string, number> | null): number {
  if (!counts) {
    return 0;
  }

  return Object.entries(counts)
    .filter(([code]) => !code.startsWith('2'))
    .reduce((sum, [, count]) => sum + count, 0);
}

export function getErrorDetails(counts: Record<string, number> | null) {
  if (!counts) {
    return {};
  }

  return Object.fromEntries(Object.entries(counts).filter(([code]) => !code.startsWith('2')));
}
