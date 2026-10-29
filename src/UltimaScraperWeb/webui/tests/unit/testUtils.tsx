import type { ReactElement, ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { render } from '@testing-library/react';
import { ThemeProvider } from '../../src/app/theme/ThemeProvider';

export function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

export function renderWithProviders(
  ui: ReactElement,
  {
    route = '/',
    queryClient = createTestQueryClient(),
    withRouter = true,
  }: {
    route?: string;
    queryClient?: QueryClient;
    withRouter?: boolean;
  } = {},
) {
  const content: ReactNode = withRouter ? <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter> : ui;

  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <ThemeProvider>{content}</ThemeProvider>
      </QueryClientProvider>,
    ),
  };
}
