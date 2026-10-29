import {
  useCallback,
  createContext,
  useContext,
  useMemo,
  type ReactNode,
} from 'react';
import { useQuery } from '@tanstack/react-query';
import { getSystemBootstrap } from '../../api/system';
import type { SystemBootstrapResponse } from '../../api/types/bootstrap';

type AppBootstrapContextValue = {
  bootstrap: SystemBootstrapResponse | null;
  isLoading: boolean;
  isFetching: boolean;
  failureCount: number;
  error: unknown;
  statusText: string;
  retryBootstrap: () => void;
};

const AppBootstrapContext = createContext<AppBootstrapContextValue | null>(null);

function getStatusText(bootstrap: SystemBootstrapResponse | null, isLoading: boolean): string {
  if (isLoading && !bootstrap) {
    return 'Connecting';
  }
  if (!bootstrap) {
    return 'Unavailable';
  }

  const setupText = bootstrap.setup.is_configured ? 'Ready' : 'Setup required';
  return `${setupText} · ${bootstrap.backend_id} · v${bootstrap.version}`;
}

export function AppBootstrapProvider({ children }: { children: ReactNode }) {
  const { data, isLoading, isFetching, failureCount, error, refetch } = useQuery({
    queryKey: ['system-bootstrap'],
    queryFn: getSystemBootstrap,
    retry: 2,
    staleTime: 15_000,
    refetchInterval: (query) => {
      const configured = query.state.data?.setup.is_configured;
      // Setup discovery needs polling, but a configured application does not.
      // Periodic bootstrap responses used to remount the startup gate whenever
      // a different API worker returned a process-local startup identifier.
      return configured ? false : 2_000;
    },
    refetchIntervalInBackground: true,
  });

  const retryBootstrap = useCallback(() => {
    void refetch();
  }, [refetch]);

  const value = useMemo<AppBootstrapContextValue>(
    () => ({
      bootstrap: data ?? null,
      isLoading,
      isFetching,
      failureCount,
      error,
      statusText: getStatusText(data ?? null, isLoading),
      retryBootstrap,
    }),
    [data, error, failureCount, isFetching, isLoading, retryBootstrap],
  );

  return (
    <AppBootstrapContext.Provider value={value}>
      {children}
    </AppBootstrapContext.Provider>
  );
}

export function useAppBootstrap(): AppBootstrapContextValue {
  const context = useContext(AppBootstrapContext);
  if (!context) {
    throw new Error('useAppBootstrap must be used within an AppBootstrapProvider');
  }
  return context;
}
