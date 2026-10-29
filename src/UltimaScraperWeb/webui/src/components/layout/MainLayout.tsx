import { useTheme } from '../../app/theme/useTheme';

export function MainLayout() {
  const {
    theme: {
      shell: { AppShell },
    },
  } = useTheme();

  return <AppShell />;
}
