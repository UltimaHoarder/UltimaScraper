import { ultimaAtlasTheme } from '../../themes/ultima-atlas/manifest';
import type { ThemeId, ThemeManifest } from './types';

export const themes = [ultimaAtlasTheme] as const satisfies readonly ThemeManifest[];

export const defaultThemeId: ThemeId = 'ultima-atlas';

export function getThemeById(themeId: ThemeId) {
  return themes.find((theme) => theme.id === themeId);
}
