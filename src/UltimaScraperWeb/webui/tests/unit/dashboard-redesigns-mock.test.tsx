import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import { DashboardRedesignsMock } from '../../src/features/mock/dashboard-redesigns/DashboardRedesignsMock';
import { DesignLab } from '../../src/features/mock/DesignLab';

describe('DashboardRedesignsMock', () => {
  it('renders all 5 dashboard concepts in the navigation header', () => {
    render(
      <MemoryRouter initialEntries={['/?category=dashboard']}>
        <DashboardRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('button', { name: /01.*Pulse Command Deck/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /02.*Acquisition Pipeline Schematic/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /03.*Incident & Triage Runbook/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /04.*Fleet & Proxy Matrix/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /05.*Workload & Queue Runway/i })).toBeInTheDocument();
  });

  it('renders in DesignLab when category=dashboard is selected', () => {
    render(
      <MemoryRouter initialEntries={['/?category=dashboard']}>
        <DesignLab />
      </MemoryRouter>
    );

    expect(screen.getByRole('button', { name: /Dashboard.*5 concepts/i })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /01.*Pulse Command Deck/i })).toBeInTheDocument();
  });

  it('renders Concept 1 (Pulse Command Deck) with KPIs, active jobs, worker array, and proxy fabric', () => {
    render(
      <MemoryRouter initialEntries={['/?category=dashboard&concept=command']}>
        <DashboardRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('region', { name: /Pulse Command Deck/i })).toBeInTheDocument();
    expect(screen.getByText(/Scraping & Disk Write Velocity/i)).toBeInTheDocument();
    expect(screen.getByText(/VIP Creator Delta Sync/i)).toBeInTheDocument();

    // Pause a running job
    const pauseButtons = screen.getAllByRole('button', { name: /^Pause$/i });
    fireEvent.click(pauseButtons[0]);
    expect(screen.getByRole('status')).toHaveTextContent(/paused/i);
  });

  it('renders Concept 2 (Acquisition Pipeline Schematic) and switches stage inspectors', () => {
    render(
      <MemoryRouter initialEntries={['/?category=dashboard&concept=topology']}>
        <DashboardRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('region', { name: /Acquisition Pipeline Schematic/i })).toBeInTheDocument();
    expect(screen.getByText(/Mount Capacity, Watermarks & Spillway Governance/i)).toBeInTheDocument();

    // Flush overflow mount
    const flushBtn = screen.getByRole('button', { name: /Flush Staging to Cold Archive/i });
    fireEvent.click(flushBtn);
    expect(screen.getByRole('status')).toHaveTextContent(/spillway cleared/i);

    // Switch to Worker Fleet Array stage node
    const workerNodeBtn = screen.getByRole('button', { name: /02 \/\/ COMPUTE.*Worker Fleet Array/i });
    fireEvent.click(workerNodeBtn);
    expect(screen.getByText(/Compute Nodes & Hardware Transcode Telemetry/i)).toBeInTheDocument();
  });

  it('renders Concept 3 (Incident & Triage Runbook) and executes 1-click remediation', () => {
    render(
      <MemoryRouter initialEntries={['/?category=dashboard&concept=triage']}>
        <DashboardRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('region', { name: /Incident & Triage Runbook/i })).toBeInTheDocument();
    expect(screen.getByText(/2 unresolved/i)).toBeInTheDocument();

    const remediateBtn = screen.getByRole('button', { name: /Requeue Failed Tasks on EU-01/i });
    fireEvent.click(remediateBtn);

    expect(screen.getByText(/1 unresolved/i)).toBeInTheDocument();
    expect(screen.getByText(/Remediation verified in preview/i)).toBeInTheDocument();
  });

  it('renders Concept 4 (Fleet & Proxy Matrix) and inspects worker dossiers', () => {
    render(
      <MemoryRouter initialEntries={['/?category=dashboard&concept=fleet']}>
        <DashboardRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('region', { name: /Fleet & Proxy Matrix/i })).toBeInTheDocument();
    expect(screen.getByRole('complementary', { name: /Selected worker dossier/i })).toBeInTheDocument();

    // Select another worker row
    const workerBtn = screen.getByRole('button', { name: /worker-de-04/i });
    fireEvent.click(workerBtn);

    expect(screen.getByRole('heading', { name: /fra-transcode-04/i })).toBeInTheDocument();
  });

  it('renders Concept 5 (Workload & Queue Runway) and inspects 4-stage job funnel', () => {
    render(
      <MemoryRouter initialEntries={['/?category=dashboard&concept=runway']}>
        <DashboardRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('region', { name: /Workload & Queue Runway/i })).toBeInTheDocument();
    expect(screen.getByRole('list', { name: /Job execution stages/i })).toBeInTheDocument();

    // Select MPS job
    const mpsBtn = screen.getByRole('button', { name: /job-9485c/i });
    fireEvent.click(mpsBtn);

    expect(screen.getByText(/STAGE FUNNEL INSPECTOR \/\/ JOB-9485C/i)).toBeInTheDocument();
  });

  it('supports switching operational scenario presets and resetting preview', () => {
    render(
      <MemoryRouter initialEntries={['/?category=dashboard&concept=command']}>
        <DashboardRedesignsMock />
      </MemoryRouter>
    );

    const surgeBtn = screen.getByRole('button', { name: /MPS Surge/i });
    fireEvent.click(surgeBtn);
    expect(screen.getByRole('status')).toHaveTextContent(/High-Throughput Surge preset/i);

    const resetBtn = screen.getByRole('button', { name: /Reset preview/i });
    fireEvent.click(resetBtn);
    expect(screen.getByRole('status')).toHaveTextContent(/reset to baseline telemetry/i);
  });
});
