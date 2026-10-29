import type { ComponentType, ReactNode } from 'react';

import type { ThemeRouteViews } from '../../shared/lib/theme/route-views';

export type ThemeId = 'ultima-atlas';

export type OperationsTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger';

export interface OperationsHeroBadge {
  label: string;
  value: string;
  tone?: OperationsTone;
}

export interface OperationsHeroProps {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  badges?: readonly OperationsHeroBadge[];
  actions?: ReactNode;
}

export interface OperationsNoticeProps {
  tone?: OperationsTone;
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
}

export interface OperationsStateProps {
  variant?: 'loading' | 'empty' | 'error';
  title: string;
  description?: string;
  actions?: ReactNode;
  compact?: boolean;
}

export interface ConfirmDialogProps {
  isOpen: boolean;
  title: string;
  description: string;
  progress?: { completed: number; total: number; failed?: number; rows?: number; table?: string };
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: 'neutral' | 'danger';
  isPending?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

export interface SidebarShellProps {
  isOpen: boolean;
  onClose: () => void;
  statusText: string;
}

export interface ThemeShell {
  AppShell: ComponentType;
  Sidebar: ComponentType<SidebarShellProps>;
}

export interface ThemePatterns {
  OperationsHero: ComponentType<OperationsHeroProps>;
  OperationsNotice: ComponentType<OperationsNoticeProps>;
  OperationsState: ComponentType<OperationsStateProps>;
  ConfirmDialog: ComponentType<ConfirmDialogProps>;
}

export interface ThemeManifest {
  id: ThemeId;
  label: string;
  description?: string;
  shell: ThemeShell;
  patterns: ThemePatterns;
  views: ThemeRouteViews;
}

export interface ThemeContextValue {
  theme: ThemeManifest;
  themes: readonly ThemeManifest[];
  setTheme: (themeId: ThemeId) => void;
}
