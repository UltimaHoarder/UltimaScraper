import type { ReactNode } from 'react';
import './WorkspacePageHeader.css';

export interface WorkspacePageHeaderBadge {
  label: string;
  value: ReactNode;
  tone?: 'neutral' | 'accent' | 'success' | 'warning' | 'danger';
}

interface WorkspacePageHeaderProps {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  icon?: ReactNode;
  meta?: ReactNode;
  badges?: readonly WorkspacePageHeaderBadge[];
  headingId?: string;
  headingLevel?: 1 | 2;
  className?: string;
}

export function WorkspacePageHeader({
  eyebrow = 'Platform',
  title,
  subtitle,
  icon = '⛭',
  meta,
  badges = [],
  headingId,
  headingLevel = 1,
  className = '',
}: WorkspacePageHeaderProps) {
  const Heading = headingLevel === 2 ? 'h2' : 'h1';

  return (
    <header className={`workspace-page-header ${className}`.trim()}>
      <div className="workspace-page-header__title">
        <span className="workspace-page-header__icon" aria-hidden="true">{icon}</span>
        <div className="workspace-page-header__copy">
          {eyebrow ? <span className="workspace-page-header__eyebrow">{eyebrow}</span> : null}
          <Heading id={headingId} className="workspace-page-header__heading">{title}</Heading>
          {subtitle ? <p className="workspace-page-header__subtitle">{subtitle}</p> : null}
        </div>
      </div>
      {(badges.length > 0 || meta) ? (
        <div className="workspace-page-header__meta">
          {badges.length > 0 ? (
            <div className="workspace-page-header__badges">
              {badges.map((badge) => (
                <span
                  className={`workspace-page-header__badge workspace-page-header__badge--${badge.tone ?? 'neutral'}`}
                  key={badge.label}
                >
                  <span>{badge.label}</span>
                  <strong>{badge.value}</strong>
                </span>
              ))}
            </div>
          ) : null}
          {meta}
        </div>
      ) : null}
    </header>
  );
}
