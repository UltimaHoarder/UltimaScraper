import type { SettingsResponse } from '../../../api/types/settings';
import type { DriveInfo } from '../../../api/types/system';
import { formatBytes as formatByteSize } from '../../../shared/lib/format';

function normalizePosixPath(path: string): string {
  if (!path) return '/';

  const isAbsolute = path.startsWith('/');
  const normalizedSegments: string[] = [];

  for (const segment of path.split('/')) {
    if (!segment || segment === '.') {
      continue;
    }

    if (segment === '..') {
      if (
        normalizedSegments.length > 0
        && normalizedSegments[normalizedSegments.length - 1] !== '..'
      ) {
        normalizedSegments.pop();
      } else if (!isAbsolute) {
        normalizedSegments.push('..');
      }
      continue;
    }

    normalizedSegments.push(segment);
  }

  const normalized = `${isAbsolute ? '/' : ''}${normalizedSegments.join('/')}`;
  return normalized || (isAbsolute ? '/' : '.');
}

function dirnamePosixPath(path: string): string {
  const normalized = normalizePosixPath(path);
  if (normalized === '/' || normalized === '.') {
    return normalized;
  }

  const lastSlashIndex = normalized.lastIndexOf('/');
  if (lastSlashIndex < 0) {
    return '.';
  }
  if (lastSlashIndex === 0) {
    return '/';
  }
  return normalized.slice(0, lastSlashIndex);
}

function normalizePath(path: string): string {
  const normalized = normalizePosixPath(path);
  if (normalized.length > 1 && normalized.endsWith('/')) {
    return normalized.slice(0, -1);
  }
  return normalized;
}

function isWithinDrive(directory: string, drivePath: string): boolean {
  const normalizedDirectory = normalizePath(directory);
  const normalizedDrivePath = normalizePath(drivePath);

  if (normalizedDrivePath === '/') {
    return normalizedDirectory.startsWith('/');
  }

  return (
    normalizedDirectory === normalizedDrivePath
    || normalizedDirectory.startsWith(`${normalizedDrivePath}/`)
  );
}

function addConfiguredDirectory(drive: DriveInfo, directory: string) {
  const normalizedDirectory = normalizePath(directory);
  if (!drive.configured_directories.includes(normalizedDirectory)) {
    drive.configured_directories.push(normalizedDirectory);
  }
  drive.directory_count = drive.configured_directories.length;
  drive.is_configured = drive.configured_directories.length > 0;
}

function inferDrivePathFromDirectories(directories: string[]): string {
  const normalizedDirectories = directories.map(normalizePath).filter(Boolean);
  if (normalizedDirectories.length === 0) return '/';
  if (normalizedDirectories.length === 1) {
    return normalizePath(dirnamePosixPath(normalizedDirectories[0]));
  }

  const [firstDirectory, ...remainingDirectories] = normalizedDirectories;
  let commonSegments = firstDirectory.split('/').filter(Boolean);
  for (const directory of remainingDirectories) {
    const segments = directory.split('/').filter(Boolean);
    let index = 0;
    while (
      index < commonSegments.length
      && index < segments.length
      && commonSegments[index] === segments[index]
    ) {
      index += 1;
    }
    commonSegments = commonSegments.slice(0, index);
    if (commonSegments.length === 0) {
      return '/';
    }
  }

  return `/${commonSegments.join('/')}`;
}

/** System views report capacity and throughput with two decimals. */
export function formatBytes(bytes: number): string {
  return formatByteSize(bytes, 2);
}

export function getWorkerGridClassName(workerCount: number): string {
  if (workerCount >= 32) return 'workers-grid workers-grid-compact';
  if (workerCount >= 16) return 'workers-grid workers-grid-dense';
  return 'workers-grid';
}

export function mergeConfiguredDrivesWithInventory(
  liveDrives: DriveInfo[],
  settings: SettingsResponse | null | undefined,
): DriveInfo[] {
  const liveDriveEntries = liveDrives.map((drive) => ({
    ...drive,
    path: normalizePath(drive.path),
    configured_directories: drive.configured_directories.map(normalizePath),
    directory_count: drive.configured_directories.length,
    is_available: drive.is_available ?? true,
  }));
  const liveDriveMap = new Map(liveDriveEntries.map((drive) => [drive.path, drive]));
  const sortedLivePaths = liveDriveEntries
    .map((drive) => drive.path)
    .sort((left, right) => right.length - left.length);
  const unavailableDriveMap = new Map<string, DriveInfo>();

  const configuredDriveGroups = settings
    ? [...settings.download_setup.drives, ...settings.metadata_setup.drives]
    : [];

  for (const driveGroup of configuredDriveGroups) {
    const configuredDirectories = driveGroup.directories.map((directory) => normalizePath(directory));
    if (configuredDirectories.length === 0) {
      continue;
    }

    const unmatchedDirectories: string[] = [];
    for (const directory of configuredDirectories) {
      const liveDrivePath = sortedLivePaths.find((drivePath) => isWithinDrive(directory, drivePath));
      if (liveDrivePath) {
        const liveDrive = liveDriveMap.get(liveDrivePath);
        if (liveDrive) {
          addConfiguredDirectory(liveDrive, directory);
        }
        continue;
      }

      unmatchedDirectories.push(directory);
    }

    if (unmatchedDirectories.length === 0) {
      continue;
    }

    const inferredDrivePath = inferDrivePathFromDirectories(unmatchedDirectories);

    for (const directory of unmatchedDirectories) {
      let unavailableDrive = unavailableDriveMap.get(inferredDrivePath);
      if (!unavailableDrive) {
        unavailableDrive = {
          path: inferredDrivePath,
          device: 'Mount unavailable',
          total_bytes: 0,
          used_bytes: 0,
          free_bytes: 0,
          percent_used: 0,
          is_configured: true,
          directory_count: 0,
          configured_directories: [],
          is_available: false,
        };
        unavailableDriveMap.set(inferredDrivePath, unavailableDrive);
      }
      addConfiguredDirectory(unavailableDrive, directory);
    }
  }

  return [...liveDriveEntries, ...Array.from(unavailableDriveMap.values()).sort((left, right) => left.path.localeCompare(right.path))];
}

export function createDriveSettingsDraft(settings: SettingsResponse) {
  return {
    downloadDirFormat: settings.download_setup.directory_format,
    downloadAltDirectoryFormats: [...settings.download_setup.alt_directory_formats],
    downloadFilenameFormat: settings.download_setup.filename_format,
    downloadTextLength: settings.download_setup.text_length,
    downloadDateFormat: settings.download_setup.date_format,
    downloadOverwrite: settings.download_setup.overwrite_files,
    stagingDirectories: settings.download_setup.staging_directories.map((directory) => ({
      ...directory,
      usage: [...directory.usage],
      policy: [...directory.policy],
    })),
    metadataDirFormat: settings.metadata_setup.directory_format,
  };
}
