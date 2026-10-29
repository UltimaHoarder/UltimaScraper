import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import { DrivesRedesignsMock } from '../../src/features/mock/drives-redesigns/DrivesRedesignsMock';
import { DesignLab } from '../../src/features/mock/DesignLab';

describe('DrivesRedesignsMock', () => {
  it('renders all 5 concepts in the navigation header', () => {
    render(
      <MemoryRouter initialEntries={['/?category=drives']}>
        <DrivesRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('button', { name: /01.*Storage Cockpit Console/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /02.*Dual-Pane Storage Architect/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /03.*Visual Flow & Ingestion Pipeline/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /04.*Capacity & Quota Commander/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /05.*Drive Studio Pro & Diagnostics/i })).toBeInTheDocument();
  });

  it('renders in DesignLab when category=drives is navigated to', () => {
    render(
      <MemoryRouter initialEntries={['/?category=drives']}>
        <DesignLab />
      </MemoryRouter>
    );

    expect(screen.getByRole('button', { name: /Drive Configure Modal/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /01.*Storage Cockpit Console/i })).toBeInTheDocument();
  });

  it('renders Concept 1 (Storage Cockpit Console) with partition strip and directory table', () => {
    render(
      <MemoryRouter initialEntries={['/?category=drives&concept=cockpit']}>
        <DrivesRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('region', { name: /Drive Cockpit Console/i })).toBeInTheDocument();
    expect(screen.getByText(/Storage Partitioning & Allocation Breakdown/i)).toBeInTheDocument();
    expect(screen.getByText(/Mount Directories & Ingestion Governance/i)).toBeInTheDocument();

    // Verify directory row exists
    expect(screen.getByText('/mnt/storage_fast/downloads/active')).toBeInTheDocument();

    // Toggle store switch
    const storeCheckbox = screen.getByRole('checkbox', {
      name: /Store files in \/mnt\/storage_fast\/downloads\/active/i,
    });
    expect(storeCheckbox).toBeChecked();
    fireEvent.click(storeCheckbox);
    expect(storeCheckbox).not.toBeChecked();

    // Open add directory tray
    const addBtn = screen.getByRole('button', { name: /\+ Add Mount Directory/i });
    fireEvent.click(addBtn);
    expect(screen.getByText(/Create Directory Assignment/i)).toBeInTheDocument();
  });

  it('renders Concept 2 (Dual-Pane Storage Architect) and switches between directories and global token engine', () => {
    render(
      <MemoryRouter initialEntries={['/?category=drives&concept=dualpane']}>
        <DrivesRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('region', { name: /^Dual-Pane Storage Architect$/i })).toBeInTheDocument();
    expect(screen.getByText(/DIRECTORIES ON THIS DRIVE/i)).toBeInTheDocument();

    // Click on Routing & Token Engine in left pane
    const tokenEngineNav = screen.getByRole('button', { name: /Routing & Token Engine/i });
    fireEvent.click(tokenEngineNav);

    // Live preview and format inputs should appear on the right
    expect(screen.getByText(/LIVE RESOLVED SAMPLE PATH/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Download directory format/i)).toBeInTheDocument();
  });

  it('renders Concept 3 (Visual Flow & Ingestion Pipeline) and triggers overflow spillway on slider adjustment', () => {
    render(
      <MemoryRouter initialEntries={['/?category=drives&concept=pipeline']}>
        <DrivesRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('region', { name: /Storage Pipeline Ingestion Flow/i })).toBeInTheDocument();
    expect(screen.getByText(/Worker Ingestion/i)).toBeInTheDocument();
    expect(screen.getByText(/Staging Quarantine/i)).toBeInTheDocument();
    expect(screen.getByText(/CLEAR TO WRITE/i)).toBeInTheDocument();

    // Adjust free space slider to 10 GB (below 50 GB threshold)
    const rangeSlider = screen.getByLabelText(/Simulate free space headroom/i);
    fireEvent.change(rangeSlider, { target: { value: '10' } });

    // Gate should now show overflow triggered
    expect(screen.getByText(/OVERFLOW TRIGGERED/i)).toBeInTheDocument();
  });

  it('renders Concept 4 (Capacity & Quota Commander) and performs batch operations', () => {
    render(
      <MemoryRouter initialEntries={['/?category=drives&concept=capacity']}>
        <DrivesRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('region', { name: /Capacity Commander Storage Studio/i })).toBeInTheDocument();
    expect(screen.getByText(/ESTIMATED RUNWAY/i)).toBeInTheDocument();
    expect(screen.getByText(/Dynamic Storage Waterlines/i)).toBeInTheDocument();

    // Select all directories
    const selectAllCheckbox = screen.getByLabelText(/Select all directories/i);
    fireEvent.click(selectAllCheckbox);

    // Sticky batch dock should appear
    expect(screen.getByRole('toolbar', { name: /Batch operations/i })).toBeInTheDocument();

    // Click batch Enable Overflow
    const enableOverflowBtn = screen.getByRole('button', { name: /Enable Overflow/i });
    fireEvent.click(enableOverflowBtn);

    // Batch dock should close after application
    expect(screen.queryByRole('toolbar', { name: /Batch operations/i })).not.toBeInTheDocument();
  });

  it('renders Concept 5 (Drive Studio Pro & Diagnostics) and runs the synthetic I/O benchmark', async () => {
    render(
      <MemoryRouter initialEntries={['/?category=drives&concept=pro']}>
        <DrivesRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('region', { name: /Drive Studio Pro Diagnostics Hub/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Synthetic I\/O/i })).toBeInTheDocument();

    // Run benchmark
    const runBtn = screen.getByRole('button', { name: /Run I\/O Benchmark/i });
    fireEvent.click(runBtn);

    // Benchmark running indicator
    expect(screen.getByText(/Benchmarking block device write latency/i)).toBeInTheDocument();

    // Wait for benchmark to finish
    await waitFor(
      () => {
        expect(screen.getByText(/SEQUENTIAL READ/i)).toBeInTheDocument();
      },
      { timeout: 3000 }
    );

    // Switch to Token Studio tab
    const tokenTab = screen.getByRole('button', { name: /Token Studio/i });
    fireEvent.click(tokenTab);

    expect(screen.getByText(/Clickable Variable Token Palette/i)).toBeInTheDocument();
    expect(screen.getByText(/Real-Time Path Resolution Sandbox/i)).toBeInTheDocument();
  });

  it('supports switching sample drives from the drive toolbar', () => {
    render(
      <MemoryRouter initialEntries={['/?category=drives&concept=cockpit']}>
        <DrivesRedesignsMock />
      </MemoryRouter>
    );

    // Switch to Archive Pool
    const archiveBtn = screen.getByRole('button', { name: /\/media\/archive_pool/i });
    fireEvent.click(archiveBtn);

    expect(screen.getByText('/media/archive_pool/bulk_media')).toBeInTheDocument();
    expect(screen.getByText(/88.0%/i)).toBeInTheDocument();

    // Switch to Offline Drive
    const offlineBtn = screen.getByRole('button', { name: /\/mnt\/offline_hdd/i });
    fireEvent.click(offlineBtn);

    expect(screen.getAllByText(/OFFLINE/i).length).toBeGreaterThan(0);
  });

  it('toggles presentation mode between modal dialog and inline studio', () => {
    render(
      <MemoryRouter initialEntries={['/?category=drives&concept=cockpit']}>
        <DrivesRedesignsMock />
      </MemoryRouter>
    );

    // Modal dialog is open by default
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // Switch to Inline Studio
    const inlineBtn = screen.getByRole('button', { name: /Inline Studio/i });
    fireEvent.click(inlineBtn);

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: /Drive Cockpit Console/i })).toBeInTheDocument();

    // Switch back to Modal Dialog
    const modalBtn = screen.getByRole('button', { name: /Modal Dialog/i });
    fireEvent.click(modalBtn);

    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // Close modal dialog
    const closeBtn = screen.getByRole('button', { name: /Close configure modal/i });
    fireEvent.click(closeBtn);

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Reopen Drive Configure Modal/i })).toBeInTheDocument();
  });
});
