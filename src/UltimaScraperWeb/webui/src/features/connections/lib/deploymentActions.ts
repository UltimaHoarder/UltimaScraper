import type { DeploymentOperation } from '../../../api/webui';

export type Action = DeploymentOperation['action'];

export const ACTION_LABELS: Record<Action, string> = {
  repair: 'Repair',
  upgrade: 'Upgrade',
  uninstall: 'Uninstall',
  services: 'Change services',
};

export const ACTION_HINTS: Record<Action, string> = {
  repair: 'Starts every service again and checks this WebUI can reach the backend.',
  upgrade: 'Moves to another image version. Data and settings are kept.',
  uninstall: 'Stops the deployment and removes this WebUI’s access to the host.',
  services: 'Turns the backend, workers or a WebUI on or off in this install. Data and settings are kept.',
};
