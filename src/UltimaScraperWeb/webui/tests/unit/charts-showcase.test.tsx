import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import { DesignLab } from '../../src/features/mock/DesignLab';
import { ChartsShowcaseMock } from '../../src/features/mock/charts-showcase/ChartsShowcaseMock';

describe('ChartsShowcaseMock & DesignLab ECharts Integration', () => {
  it('renders within DesignLab as a category with concept buttons', () => {
    render(
      <MemoryRouter initialEntries={['/?category=charts']}>
        <DesignLab />
      </MemoryRouter>
    );

    // Categories header
    expect(screen.getByRole('button', { name: /ECharts Showcase/i })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /Users & Creators/i })).toBeInTheDocument();

    // Concepts navigation inside charts lab
    expect(screen.getByRole('button', { name: /00.*Unified Dashboard/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /01.*Ingestion Telemetry/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /02.*Media Vault Storage/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /03.*24\/7 Activity Matrix/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /04.*Roster Health Radar/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /05.*Pipeline Funnel/i })).toBeInTheDocument();
  });

  it('renders all 5 charts in the Overview concept', () => {
    render(
      <MemoryRouter initialEntries={['/?category=charts&concept=overview']}>
        <ChartsShowcaseMock />
      </MemoryRouter>
    );

    // Check headings of all 5 charts
    expect(screen.getByText(/01 · Live Ingestion Telemetry & Concurrency/i)).toBeInTheDocument();
    expect(screen.getByText(/02 · Media Vault Storage Breakdown/i)).toBeInTheDocument();
    expect(screen.getByText(/03 · 24\/7 Download Bandwidth Heatmap/i)).toBeInTheDocument();
    expect(screen.getByText(/04 · Creator Archival Health & Completeness/i)).toBeInTheDocument();
    expect(screen.getByText(/05 · Scraper Ingestion Pipeline Funnel/i)).toBeInTheDocument();

    // Key metrics bar
    expect(screen.getByText(/Total Vault Size/i)).toBeInTheDocument();
    expect(screen.getByText(/Live Throughput/i)).toBeInTheDocument();
    expect(screen.getByText(/Active Workers/i)).toBeInTheDocument();
    expect(screen.getByText(/Pipeline Verified/i)).toBeInTheDocument();
  });

  it('switches to individual concept view (e.g. Telemetry)', () => {
    render(
      <MemoryRouter initialEntries={['/?category=charts&concept=telemetry']}>
        <ChartsShowcaseMock />
      </MemoryRouter>
    );

    expect(screen.getByText(/01 · Live Ingestion Telemetry & Concurrency/i)).toBeInTheDocument();
    expect(screen.queryByText(/02 · Media Vault Storage Breakdown/i)).not.toBeInTheDocument();
  });

  it('switches to Media Vault Storage concept', () => {
    render(
      <MemoryRouter initialEntries={['/?category=charts&concept=storage']}>
        <ChartsShowcaseMock />
      </MemoryRouter>
    );

    expect(screen.getByText(/02 · Media Vault Storage Breakdown/i)).toBeInTheDocument();
    expect(screen.queryByText(/01 · Live Ingestion Telemetry & Concurrency/i)).not.toBeInTheDocument();
  });

  it('toggles live streaming simulation mode', () => {
    render(
      <MemoryRouter initialEntries={['/?category=charts']}>
        <ChartsShowcaseMock />
      </MemoryRouter>
    );

    const streamBtn = screen.getByRole('button', { name: /Simulate Stream/i });
    expect(streamBtn).toBeInTheDocument();
    expect(streamBtn).toHaveAttribute('aria-pressed', 'false');

    fireEvent.click(streamBtn);
    expect(screen.getByRole('button', { name: /Pause Stream/i })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText(/Live Streaming Active/i)).toBeInTheDocument();
  });

  it('toggles renderer between Canvas and SVG', () => {
    render(
      <MemoryRouter initialEntries={['/?category=charts']}>
        <ChartsShowcaseMock />
      </MemoryRouter>
    );

    const toggleBtn = screen.getByRole('button', { name: /Switch to SVG/i });
    fireEvent.click(toggleBtn);

    expect(screen.getByText(/Renderer: SVG/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Switch to Canvas/i })).toBeInTheDocument();
  });

  it('allows selecting timeframe presets', () => {
    render(
      <MemoryRouter initialEntries={['/?category=charts']}>
        <ChartsShowcaseMock />
      </MemoryRouter>
    );

    const btn24h = screen.getByRole('button', { name: '24h' });
    fireEvent.click(btn24h);

    expect(btn24h).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText(/Timeframe: 24h/i)).toBeInTheDocument();
  });
});
