import type { ReactNode } from 'react';

import type {
  OperationsHeroBadge,
  OperationsNoticeProps,
  OperationsStateProps,
} from '../../../app/theme/types';

import './investigation-kit.css';

interface InvestigationHeaderProps {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  badges?: readonly OperationsHeroBadge[];
  actions?: ReactNode;
  runtimeLabel?: string;
  className?: string;
}

interface TerminalSlabProps {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}

interface WarningPlateProps extends OperationsNoticeProps {
  className?: string;
}

interface InvestigationStateProps extends OperationsStateProps {
  className?: string;
}

export function InvestigationHeader({
  eyebrow,
  title,
  subtitle,
  badges = [],
  actions,
  runtimeLabel = 'Operator investigation mode',
  className = '',
}: InvestigationHeaderProps) {
  return (
    <section className={`ultimur-v2-header ${className}`.trim()}>
      <div className="ultimur-v2-header__main">
        <div className="ultimur-v2-header__copy">
          {eyebrow ? <div className="ultimur-v2-header__eyebrow">{eyebrow}</div> : null}
          <h1 className="ultimur-v2-header__title">{title}</h1>
          {subtitle ? <p className="ultimur-v2-header__subtitle">{subtitle}</p> : null}
        </div>
        <div className="ultimur-v2-header__runtime">
          <span className="ultimur-v2-header__runtime-label">Mode</span>
          <span className="ultimur-v2-header__runtime-value">{runtimeLabel}</span>
        </div>
      </div>

      {actions ? <div className="ultimur-v2-header__actions">{actions}</div> : null}

      {badges.length > 0 ? (
        <div className="ultimur-v2-header__badges">
          {badges.map((badge) => (
            <div
              key={`${badge.label}-${badge.value}`}
              className={`ultimur-v2-badge ultimur-v2-badge--${badge.tone ?? 'neutral'}`}
            >
              <span className="ultimur-v2-badge__label">{badge.label}</span>
              <strong className="ultimur-v2-badge__value">{badge.value}</strong>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

export function TerminalSlab({
  eyebrow,
  title,
  subtitle,
  actions,
  children,
  className = '',
}: TerminalSlabProps) {
  return (
    <section className={`ultimur-v2-slab ${className}`.trim()}>
      <div className="ultimur-v2-slab__header">
        <div className="ultimur-v2-slab__copy">
          {eyebrow ? <div className="ultimur-v2-slab__eyebrow">{eyebrow}</div> : null}
          <h2 className="ultimur-v2-slab__title">{title}</h2>
          {subtitle ? <p className="ultimur-v2-slab__subtitle">{subtitle}</p> : null}
        </div>
        {actions ? <div className="ultimur-v2-slab__actions">{actions}</div> : null}
      </div>
      <div className="ultimur-v2-slab__body">{children}</div>
    </section>
  );
}

export function WarningPlate({
  tone = 'neutral',
  title,
  children,
  actions,
  className = '',
}: WarningPlateProps) {
  return (
    <section className={`ultimur-v2-warning ultimur-v2-warning--${tone} ${className}`.trim()}>
      <div className="ultimur-v2-warning__copy">
        <strong className="ultimur-v2-warning__title">{title}</strong>
        {children ? <div className="ultimur-v2-warning__body">{children}</div> : null}
      </div>
      {actions ? <div className="ultimur-v2-warning__actions">{actions}</div> : null}
    </section>
  );
}

export function InvestigationState({
  variant = 'empty',
  title,
  description,
  actions,
  compact = false,
  className = '',
}: InvestigationStateProps) {
  return (
    <div
      className={`ultimur-v2-state ultimur-v2-state--${variant} ${compact ? 'ultimur-v2-state--compact' : ''} ${className}`.trim()}
      role={variant === 'loading' ? 'status' : undefined}
      aria-busy={variant === 'loading' ? true : undefined}
    >
      {variant === 'loading' && <span className="ops-state-spinner" aria-hidden="true" />}
      <div className="ultimur-v2-state__copy">
        <strong className="ultimur-v2-state__title">{title}</strong>
        {description ? <p className="ultimur-v2-state__description">{description}</p> : null}
      </div>
      {actions ? <div className="ultimur-v2-state__actions">{actions}</div> : null}
    </div>
  );
}
