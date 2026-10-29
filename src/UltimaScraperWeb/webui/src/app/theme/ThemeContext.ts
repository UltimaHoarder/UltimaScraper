import { createContext } from 'react';

import type { ThemeContextValue } from './types';

export const ThemeContext = createContext<ThemeContextValue | null>(null);
