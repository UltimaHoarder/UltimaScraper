import type {
  OperationsHeroProps,
  OperationsNoticeProps,
  OperationsStateProps,
} from '../../../app/theme/types';
import { useTheme } from '../../../app/theme/useTheme';

export function OperationsHero(props: OperationsHeroProps) {
  const {
    theme: {
      patterns: { OperationsHero: OperationsHeroComponent },
    },
  } = useTheme();

  return <OperationsHeroComponent {...props} />;
}

export function OperationsNotice(props: OperationsNoticeProps) {
  const {
    theme: {
      patterns: { OperationsNotice: OperationsNoticeComponent },
    },
  } = useTheme();

  return <OperationsNoticeComponent {...props} />;
}

export function OperationsState(props: OperationsStateProps) {
  const {
    theme: {
      patterns: { OperationsState: OperationsStateComponent },
    },
  } = useTheme();

  return <OperationsStateComponent {...props} />;
}
