import { screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { ThemeProvider } from '../../src/app/theme/ThemeProvider';
import { useTheme } from '../../src/app/theme/useTheme';
import { ThemeSettingsSection } from '../../src/features/settings/components/ThemeSettingsSection';
import { renderWithProviders } from './testUtils';

function ThemeProbe() {
  const { theme, themes } = useTheme();

  return (
    <div>
      <span>{theme.id}</span>
      <span>{theme.label}</span>
      <span>{theme.description}</span>
      <span>{themes.length}</span>
    </div>
  );
}

describe('ThemeProvider', () => {
  it('applies the default theme to the document root and exposes the active manifest', async () => {
    renderWithProviders(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
      { withRouter: false },
    );

    await waitFor(() => {
      expect(document.documentElement.dataset.theme).toBe('ultima-atlas');
    });

    expect(screen.getByText('ultima-atlas')).toBeInTheDocument();
    expect(screen.getByText('Ultima Atlas')).toBeInTheDocument();
    expect(
      screen.getByText(/Industrial data acquisition systems/i),
    ).toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(localStorage.getItem('usr_theme')).toBe('ultima-atlas');
  });

  it('renders registered theme in settings appearance when single theme is available', async () => {
    renderWithProviders(
      <ThemeProvider>
        <ThemeSettingsSection />
      </ThemeProvider>,
      { withRouter: false },
    );

    expect(screen.getByText('Ultima Atlas')).toBeInTheDocument();
    expect(screen.queryByRole('combobox', { name: 'Active theme' })).not.toBeInTheDocument();
    expect(screen.getByText(/The current theme is registered and active/i)).toBeInTheDocument();
  });

  it('falls back when a removed theme selection is stored', async () => {
    localStorage.setItem('usr_theme', 'ultimur-v1');

    renderWithProviders(
      <ThemeProvider>
        <ThemeProbe />
      </ThemeProvider>,
      { withRouter: false },
    );

    await waitFor(() => {
      expect(document.documentElement.dataset.theme).toBe('ultima-atlas');
    });

    expect(screen.getByText('ultima-atlas')).toBeInTheDocument();
    expect(screen.getByText('Ultima Atlas')).toBeInTheDocument();
    expect(localStorage.getItem('usr_theme')).toBe('ultima-atlas');
  });

  it('restores the Atlas selection on reload', async () => {
    localStorage.setItem('usr_theme', 'ultima-atlas');
    renderWithProviders(<ThemeProbe />, { withRouter: false });
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('ultima-atlas'));
    expect(screen.getByText('Ultima Atlas')).toBeInTheDocument();
  });
});
