import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { getNavigationSections } from '../../src/components/layout/navigation';
import { DevModeGate } from '../../src/features/settings/components/DevModeGate';
import { DeveloperSettingsSection } from '../../src/features/settings/components/DeveloperSettingsSection';

const navPaths = (devMode: boolean) =>
  getNavigationSections(devMode).flatMap((section) => section.items.map((item) => item.path));

describe('Developer mode', () => {
  it('keeps Plugins and Mock out of the navigation until it is on', () => {
    expect(navPaths(false)).not.toContain('/plugins');
    expect(navPaths(false)).not.toContain('/mock');
    expect(navPaths(true)).toEqual(expect.arrayContaining(['/plugins', '/mock']));
  });

  it('is off by default and opens gated pages once switched on', () => {
    render(
      <MemoryRouter>
        <DeveloperSettingsSection />
        <DevModeGate>
          <p>Plugin workspace</p>
        </DevModeGate>
      </MemoryRouter>,
    );

    const toggle = screen.getByRole('checkbox', { name: 'Developer mode' });
    expect(toggle).not.toBeChecked();
    expect(screen.queryByText('Plugin workspace')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Developer settings' })).toHaveAttribute(
      'href',
      '/settings?tab=developer',
    );

    act(() => {
      fireEvent.click(toggle);
    });
    expect(screen.getByText('Plugin workspace')).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem('usr_webui_preferences') ?? '{}').devMode).toBe(true);
  });
});
