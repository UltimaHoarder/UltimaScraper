import type { ConfirmDialogProps } from '../../app/theme/types';
import { useTheme } from '../../app/theme/useTheme';

export function ConfirmDialog(props: ConfirmDialogProps) {
  const {
    theme: {
      patterns: { ConfirmDialog: ConfirmDialogComponent },
    },
  } = useTheme();

  return <ConfirmDialogComponent {...props} />;
}
