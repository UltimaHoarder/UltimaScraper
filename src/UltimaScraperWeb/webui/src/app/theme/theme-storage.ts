import { readStorage, writeStorage } from '../../shared/lib/browserStorage';
import type { ThemeId } from './types';

const THEME_STORAGE_KEY = 'usr_theme';

function isThemeId(value: string | null): value is ThemeId {
  return value === 'ultima-atlas';
}

export function loadStoredThemeId(defaultThemeId: ThemeId): ThemeId {
  const storedThemeId = readStorage(THEME_STORAGE_KEY);
  return isThemeId(storedThemeId) ? storedThemeId : defaultThemeId;
}

export function persistThemeId(themeId: ThemeId) {
  writeStorage(THEME_STORAGE_KEY, themeId);
}
