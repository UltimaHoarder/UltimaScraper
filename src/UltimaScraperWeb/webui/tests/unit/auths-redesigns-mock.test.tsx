import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import { AuthsRedesignsMock } from '../../src/features/mock/auths-redesigns/AuthsRedesignsMock';
import { DesignLab } from '../../src/features/mock/DesignLab';

describe('AuthsRedesignsMock', () => {
  it('renders all 5 concepts in the navigation header', () => {
    render(
      <MemoryRouter initialEntries={['/?category=auths']}>
        <AuthsRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('button', { name: /01.*Fleet Credential Vault/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /02.*Session Sentinel/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /03.*Rapid cURL Ingestion/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /04.*Performer Account Matrix/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /05.*Identity & Verification/i })).toBeInTheDocument();
  });

  it('renders in DesignLab when category=auths is selected', () => {
    render(
      <MemoryRouter initialEntries={['/?category=auths']}>
        <DesignLab />
      </MemoryRouter>
    );

    expect(screen.getByRole('button', { name: /Auths & Accounts.*5 concepts/i })).toHaveAttribute(
      'aria-pressed',
      'true'
    );
    expect(screen.getByRole('button', { name: /01.*Fleet Credential Vault/i })).toBeInTheDocument();
  });

  it('renders Concept 1 (Fleet Credential Vault) and supports active toggling and testing', () => {
    render(
      <MemoryRouter initialEntries={['/?category=auths&concept=vault']}>
        <AuthsRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('region', { name: /Fleet Credential Vault/i })).toBeInTheDocument();
    expect(screen.getByText(/TOTAL SESSIONS/i)).toBeInTheDocument();
    expect(screen.getByText(/FLEET HEALTH/i)).toBeInTheDocument();
    expect(screen.getByText(/@vip_operator_01/i)).toBeInTheDocument();

    // Verify search input
    const searchInput = screen.getByPlaceholderText(/Search credentials by handle/i);
    fireEvent.change(searchInput, { target: { value: 'fansly' } });
    expect(screen.getAllByText(/@nova_archivist/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText(/@vip_operator_01/i)).not.toBeInTheDocument();
  });

  it('renders Concept 2 (Session Sentinel & Health Triage) and allows switching triage funnel tabs', () => {
    render(
      <MemoryRouter initialEntries={['/?category=auths&concept=sentinel']}>
        <AuthsRedesignsMock />
      </MemoryRouter>
    );

    expect(
      screen.getByRole('region', { name: /Session Sentinel and Health Triage/i })
    ).toBeInTheDocument();
    expect(screen.getByText(/Fleet Authentication Triage & Incident Runbook/i)).toBeInTheDocument();

    // Switch funnel tab to Challenges
    const challengesTab = screen.getByRole('button', { name: /Challenges/i });
    fireEvent.click(challengesTab);
    expect(screen.getByText(/@sky_crawler_uk/i)).toBeInTheDocument();
  });

  it('renders Concept 3 (Rapid cURL Ingestion Studio) and allows live editing and decoding', () => {
    render(
      <MemoryRouter initialEntries={['/?category=auths&concept=studio']}>
        <AuthsRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('region', { name: /Rapid cURL Ingestion Studio/i })).toBeInTheDocument();
    expect(screen.getByText(/Live Request Terminal/i)).toBeInTheDocument();
    expect(screen.getByText(/LIVE TOKEN PARAMETER DECODER/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Ingest to Fleet/i })).toBeInTheDocument();
  });

  it('renders Concept 4 (Performer Account Matrix & Spender Fortress) and toggles spender protections', () => {
    render(
      <MemoryRouter initialEntries={['/?category=auths&concept=matrix']}>
        <AuthsRedesignsMock />
      </MemoryRouter>
    );

    expect(
      screen.getByRole('region', { name: /Performer Account Matrix and Spender Fortress/i })
    ).toBeInTheDocument();
    expect(screen.getAllByText(/SPENDER FORTRESS/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/PROTECTED FINANCIAL SHIELD/i)).toBeInTheDocument();

    // Verify table rendered with row
    expect(screen.getByText(/@vip_operator_01/i)).toBeInTheDocument();
  });

  it('renders Concept 5 (Identity & Verification Runway) and supports mobile QR inspection', () => {
    render(
      <MemoryRouter initialEntries={['/?category=auths&concept=runway']}>
        <AuthsRedesignsMock />
      </MemoryRouter>
    );

    expect(screen.getByRole('region', { name: /Identity and Verification Runway/i })).toBeInTheDocument();
    expect(screen.getByText(/Session Ingestion/i)).toBeInTheDocument();
    expect(screen.getByText(/Compliance Clearance/i)).toBeInTheDocument();
    expect(screen.getByText(/Scan to Complete Verification on Mobile/i)).toBeInTheDocument();
  });

  it('supports scenario presets and reset preview', () => {
    render(
      <MemoryRouter initialEntries={['/?category=auths&concept=vault']}>
        <AuthsRedesignsMock />
      </MemoryRouter>
    );

    const resetBtn = screen.getByRole('button', { name: /Reset preview/i });
    fireEvent.click(resetBtn);

    expect(
      screen.getByText(/Auths Design Lab preview state has been reset/i)
    ).toBeInTheDocument();
  });
});
