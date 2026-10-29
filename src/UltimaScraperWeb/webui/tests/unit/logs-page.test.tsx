import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { LogViewer, type LogEntry } from '../../src/components/logs/LogViewer';
import { LogsPage } from '../../src/themes/ultima-atlas/views/logs/LogsPage';

// Mock useWebSocket
let mockWebSocketHandler: ((event: unknown) => void) | null = null;

vi.mock('../../src/hooks/useWebSocket', () => ({
  useWebSocket: ({ onMessage }: { onMessage?: (event: unknown) => void }) => {
    mockWebSocketHandler = onMessage ?? null;
    return {
      isConnected: true,
      lastMessage: null,
      lastActivity: Date.now(),
      send: vi.fn(),
      reconnect: vi.fn(),
    };
  },
}));

vi.mock('../../src/api/http', () => ({
  getWebSocketBaseUrl: () => 'ws://127.0.0.1:4173',
}));

describe('LogsPage & LogViewer (Atlas Redesign)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockWebSocketHandler = null;
  });

  const sampleLogs: LogEntry[] = [
    {
      timestamp: '2026-10-10T18:00:00.000Z',
      level: 'info',
      message: 'Worker pool initialized with 4 workers',
      category: 'workers',
      source: 'pool.init',
    },
    {
      timestamp: '2026-10-10T18:01:00.000Z',
      level: 'warning',
      message: 'High latency detected on proxy http://proxy.local:8080',
      category: 'network',
      source: 'proxy.check',
    },
    {
      timestamp: '2026-10-10T18:02:00.000Z',
      level: 'error',
      message: 'Authentication failed for session onlyfans-alice: token expired',
      category: 'jobs',
      source: 'auth.client',
    },
    {
      timestamp: '2026-10-10T18:03:00.000Z',
      level: 'debug',
      message: 'Cache hit for media record 987654321',
      category: 'downloads',
      source: 'media.cache',
    },
  ];

  it('renders LogsPage with Atlas OperationsHero and telemetry badges', () => {
    render(<LogsPage />);

    expect(screen.getByText('01 // Telemetry')).toBeInTheDocument();
    expect(screen.getByText('Runtime Logs')).toBeInTheDocument();
    expect(screen.getByText(/Real-time event stream/i)).toBeInTheDocument();
    expect(screen.getByText('Buffered Events')).toBeInTheDocument();
    expect(screen.getByText('Stream Status')).toBeInTheDocument();
  });

  it('displays log entries with formatted levels, timestamps, categories, and sources', () => {
    render(<LogViewer initialLogs={sampleLogs} />);

    expect(screen.getByText('Worker pool initialized with 4 workers')).toBeInTheDocument();
    expect(screen.getByText('High latency detected on proxy http://proxy.local:8080')).toBeInTheDocument();
    expect(screen.getByText('Authentication failed for session onlyfans-alice: token expired')).toBeInTheDocument();
    expect(screen.getByText('Cache hit for media record 987654321')).toBeInTheDocument();

    expect(screen.getByText('[WORKERS]')).toBeInTheDocument();
    expect(screen.getByText('[NETWORK]')).toBeInTheDocument();
    expect(screen.getByText('[JOBS]')).toBeInTheDocument();
    expect(screen.getByText('[DOWNLOADS]')).toBeInTheDocument();
  });

  it('filters log stream by severity level', () => {
    render(<LogViewer initialLogs={sampleLogs} />);

    // Click on ERROR filter pill
    const errorPill = screen.getByRole('button', { name: /error 1/i });
    fireEvent.click(errorPill);

    expect(screen.getByText('Authentication failed for session onlyfans-alice: token expired')).toBeInTheDocument();
    expect(screen.queryByText('Worker pool initialized with 4 workers')).not.toBeInTheDocument();
    expect(screen.queryByText('High latency detected on proxy http://proxy.local:8080')).not.toBeInTheDocument();

    // Click on WARN filter pill
    const warnPill = screen.getByRole('button', { name: /warn 1/i });
    fireEvent.click(warnPill);

    expect(screen.getByText('High latency detected on proxy http://proxy.local:8080')).toBeInTheDocument();
    expect(screen.queryByText('Authentication failed for session onlyfans-alice: token expired')).not.toBeInTheDocument();
  });

  it('filters log stream by category', () => {
    render(<LogViewer initialLogs={sampleLogs} />);

    const jobsCategoryBtn = screen.getByRole('button', { name: 'JOBS' });
    fireEvent.click(jobsCategoryBtn);

    expect(screen.getByText('Authentication failed for session onlyfans-alice: token expired')).toBeInTheDocument();
    expect(screen.queryByText('Worker pool initialized with 4 workers')).not.toBeInTheDocument();
  });

  it('searches log entries by text query and allows clearing', () => {
    render(<LogViewer initialLogs={sampleLogs} />);

    const searchInput = screen.getByPlaceholderText(/filter log text/i);
    fireEvent.change(searchInput, { target: { value: 'proxy.local' } });

    expect(screen.getByText(/High latency detected/i)).toBeInTheDocument();
    expect(screen.queryByText('Worker pool initialized with 4 workers')).not.toBeInTheDocument();

    // Clear search
    const clearSearchBtn = screen.getByLabelText(/clear search/i);
    fireEvent.click(clearSearchBtn);

    expect(screen.getByText('Worker pool initialized with 4 workers')).toBeInTheDocument();
  });

  it('clears log buffer when clicking Clear button', () => {
    render(<LogViewer initialLogs={sampleLogs} />);

    expect(screen.getByText('Worker pool initialized with 4 workers')).toBeInTheDocument();

    const clearBtn = screen.getByRole('button', { name: /clear/i });
    fireEvent.click(clearBtn);

    expect(screen.queryByText('Worker pool initialized with 4 workers')).not.toBeInTheDocument();
    expect(screen.getByText(/Awaiting Telemetry Stream/i)).toBeInTheDocument();
  });

  it('toggles stream pause and queue release', () => {
    render(<LogViewer initialLogs={sampleLogs} />);

    const pauseBtn = screen.getByRole('button', { name: /pause stream/i });
    fireEvent.click(pauseBtn);

    expect(screen.getByRole('button', { name: /resume/i })).toBeInTheDocument();

    // While paused, emit an incoming log event
    act(() => {
      if (mockWebSocketHandler) {
        mockWebSocketHandler({
          type: 'log',
          level: 'info',
          message: 'Paused buffer test message',
          category: 'system',
        });
      }
    });

    // Message shouldn't show up yet while paused
    expect(screen.queryByText('Paused buffer test message')).not.toBeInTheDocument();

    // Resume stream
    const resumeBtn = screen.getByRole('button', { name: /resume/i });
    fireEvent.click(resumeBtn);

    // Message is now released and displayed
    expect(screen.getByText('Paused buffer test message')).toBeInTheDocument();
  });

  it('supports exporting and copying logs', async () => {
    const writeTextMock = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, {
      clipboard: {
        writeText: writeTextMock,
      },
    });
    render(<LogViewer initialLogs={sampleLogs} />);

    const copyBtn = screen.getByRole('button', { name: /^copy$/i });
    fireEvent.click(copyBtn);

    expect(writeTextMock).toHaveBeenCalled();
  });

  it('allows resetting all active filters when 0 results match', () => {
    render(<LogViewer initialLogs={sampleLogs} />);

    const searchInput = screen.getByPlaceholderText(/filter log text/i);
    fireEvent.change(searchInput, { target: { value: 'nonexistent-query-string-12345' } });

    expect(screen.getByText(/No Matching Log Records/i)).toBeInTheDocument();

    const resetBtn = screen.getByRole('button', { name: /reset active filters/i });
    fireEvent.click(resetBtn);

    expect(screen.getByText('Worker pool initialized with 4 workers')).toBeInTheDocument();
  });
});
