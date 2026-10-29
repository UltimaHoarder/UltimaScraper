import type {
  OperationsHeroProps,
  OperationsNoticeProps,
  OperationsStateProps,
} from '../../../app/theme/types';

import {
  InvestigationHeader,
  InvestigationState,
  WarningPlate,
} from './InvestigationKit';
import './operations.css';

export function OperationsHero({
  eyebrow,
  title,
  subtitle,
  badges = [],
  actions,
}: OperationsHeroProps) {
  return (
    <InvestigationHeader
      eyebrow={eyebrow}
      title={title}
      subtitle={subtitle}
      badges={badges}
      actions={actions}
      className="ops-hero ultimur-ops-hero"
    />
  );
}

export function OperationsNotice({
  tone = 'neutral',
  title,
  children,
  actions,
}: OperationsNoticeProps) {
  return (
    <WarningPlate
      tone={tone}
      title={title}
      actions={actions}
      className="ops-notice ultimur-ops-notice"
    >
      {children}
    </WarningPlate>
  );
}

export function OperationsState({
  variant = 'empty',
  title,
  description,
  actions,
  compact = false,
}: OperationsStateProps) {
  return (
    <InvestigationState
      variant={variant}
      title={title}
      description={description}
      actions={actions}
      compact={compact}
      className={`ops-state ultimur-ops-state ops-state-${variant}`}
    />
  );
}
