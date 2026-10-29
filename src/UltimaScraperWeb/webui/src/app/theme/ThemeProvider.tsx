import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import { defaultThemeId, getThemeById, themes } from './theme-registry';
import { loadStoredThemeId, persistThemeId } from './theme-storage';
import { ThemeContext } from './ThemeContext';
import type { ThemeContextValue, ThemeId } from './types';

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [activeThemeId, setActiveThemeId] = useState<ThemeId>(() => loadStoredThemeId(defaultThemeId));

  const theme = useMemo(
    () => getThemeById(activeThemeId) ?? getThemeById(defaultThemeId),
    [activeThemeId]
  );

  const setTheme = useCallback((themeId: ThemeId) => {
    setActiveThemeId(themeId);
  }, []);

  useEffect(() => {
    if (!theme) {
      return;
    }

    document.documentElement.dataset.theme = theme.id;
    persistThemeId(theme.id);
  }, [theme]);

  const value = useMemo<ThemeContextValue>(() => {
    if (!theme) {
      return {
        theme: getThemeById(defaultThemeId)!,
        themes,
        setTheme,
      };
    }

    return {
      theme,
      themes,
      setTheme,
    };
  }, [setTheme, theme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
