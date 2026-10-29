export const SETUP_STEP_LABELS = [
  'Database',
  'Redis',
  'Storage & Network',
  'DRM',
  'Auths',
  'Review',
];

export function getSetupErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }

  const apiError = error as {
    response?: {
      data?: {
        detail?: string;
      };
    };
  };

  return apiError.response?.data?.detail || fallback;
}
