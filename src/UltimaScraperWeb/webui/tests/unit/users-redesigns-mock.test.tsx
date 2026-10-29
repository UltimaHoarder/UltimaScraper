import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import { UsersRedesignsMock } from '../../src/features/mock/users-redesigns/UsersRedesignsMock';
import { DesignLab } from '../../src/features/mock/DesignLab';

describe('UsersRedesignsMock', () => {
  it('renders all 5 concepts in the navigation header', () => {
    render(
      <MemoryRouter initialEntries={['/?category=users']}>
        <UsersRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('button', { name: /01.*Creator Dossier/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /02.*Roster Matrix/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /03.*Visual Showcase/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /04.*Sync Radar/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /05.*Taxonomy Studio/i })).toBeInTheDocument();
  });

  it('renders Concept 1 (Creator Dossier) with list and details', () => {
    render(
      <MemoryRouter initialEntries={['/?category=users&concept=dossier']}>
        <UsersRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('region', { name: /Creator Dossier/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Trigger Scrape/i })).toBeInTheDocument();
    expect(screen.getByText(/Asset Vault Telemetry/i)).toBeInTheDocument();
  });

  it('switches to Concept 2 (Roster Matrix) and supports bulk selection', () => {
    render(
      <MemoryRouter initialEntries={['/?category=users&concept=matrix']}>
        <UsersRedesignsMock />
      </MemoryRouter>
    );

    const matrixTable = screen.getByRole('table', { name: /Roster Matrix/i });
    expect(matrixTable).toBeInTheDocument();

    // Select all visible creators
    const selectAllCheckbox = screen.getByRole('checkbox', { name: /Select all visible creators/i });
    fireEvent.click(selectAllCheckbox);

    // Sticky batch bar should appear
    expect(screen.getByRole('toolbar', { name: /Batch operations/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Scrape Selected/i })).toBeInTheDocument();
  });

  it('switches to Concept 3 (Visual Showcase) and renders creator cards', () => {
    render(
      <MemoryRouter initialEntries={['/?category=users&concept=showcase']}>
        <UsersRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByText(/visual dossiers/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Compact/i })).toBeInTheDocument();
  });

  it('switches to Concept 4 (Sync Radar) and displays freshness swimlanes', () => {
    render(
      <MemoryRouter initialEntries={['/?category=users&concept=radar']}>
        <UsersRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('heading', { name: /Overdue For Sync/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Never Scraped/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Watched Streams/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Fresh & Synced/i })).toBeInTheDocument();
  });

  it('switches to Concept 5 (Taxonomy Studio) and supports 1-click presets', () => {
    render(
      <MemoryRouter initialEntries={['/?category=users&concept=taxonomy']}>
        <UsersRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByText(/1-Click Taxonomy Stampers/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Solo Woman \(Hetero\)/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Confirm & Lock Taxonomy/i })).toBeInTheDocument();
  });

  it('filters creators by identifier search query', () => {
    render(
      <MemoryRouter initialEntries={['/?category=users&concept=matrix']}>
        <UsersRedesignsMock />
      </MemoryRouter>
    );

    const identifierInput = screen.getByPlaceholderText(/Search by identifier…/i);
    fireEvent.change(identifierInput, { target: { value: 'luna' } });

    expect(screen.getByText(/1 \/ 10 visible/i)).toBeInTheDocument();
  });

  it('filters creators by description search query', () => {
    render(
      <MemoryRouter initialEntries={['/?category=users&concept=matrix']}>
        <UsersRedesignsMock />
      </MemoryRouter>
    );

    const descInput = screen.getByPlaceholderText(/Search by description…/i);
    fireEvent.change(descInput, { target: { value: 'electronic music' } });

    expect(screen.getByText(/1 \/ 10 visible/i)).toBeInTheDocument();
  });

  it('opens advanced filters modal, applies a preset loadout, and displays active pill', () => {
    render(
      <MemoryRouter initialEntries={['/?category=users&concept=matrix']}>
        <UsersRedesignsMock />
      </MemoryRouter>
    );

    const filtersBtn = screen.getByRole('button', { name: /Open advanced filters modal/i });
    fireEvent.click(filtersBtn);

    expect(screen.getByRole('dialog', { name: /Advanced Creator Filters/i })).toBeInTheDocument();

    const loadoutSelect = screen.getByLabelText(/Preset Search Loadouts/i);
    fireEvent.change(loadoutSelect, { target: { value: 'Free Exploratory' } });

    const applyCloseBtn = screen.getByRole('button', { name: /Apply & Close/i });
    fireEvent.click(applyCloseBtn);

    expect(screen.queryByRole('dialog', { name: /Advanced Creator Filters/i })).not.toBeInTheDocument();
    expect(screen.getByText('Free Exploratory')).toBeInTheDocument();
  });

  it('opens advanced filters modal and displays filter badge', () => {
    render(
      <MemoryRouter initialEntries={['/?category=users&concept=matrix']}>
        <UsersRedesignsMock />
      </MemoryRouter>
    );

    const filtersBtn = screen.getByRole('button', { name: /Open advanced filters modal/i });
    fireEvent.click(filtersBtn);

    expect(screen.getByRole('dialog', { name: /Advanced Creator Filters/i })).toBeInTheDocument();

    const minPriceInput = screen.getByLabelText(/Min Price \(\$\)/i);
    fireEvent.change(minPriceInput, { target: { value: '15' } });

    const applyCloseBtn = screen.getByRole('button', { name: /Apply & Close/i });
    fireEvent.click(applyCloseBtn);

    expect(screen.queryByRole('dialog', { name: /Advanced Creator Filters/i })).not.toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument(); // filter count badge
  });

  it('renders within DesignLab as a primary category', () => {
    render(
      <MemoryRouter initialEntries={['/?category=users']}>
        <DesignLab />
      </MemoryRouter>
    );

    expect(screen.getByRole('button', { name: /Users & Creators/i })).toHaveAttribute('aria-pressed', 'true');
  });
});
