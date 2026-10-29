import { useState, useMemo } from 'react';

export type DriveHealthState = 'healthy' | 'warning' | 'critical' | 'offline';
export type SetupType = 'download' | 'metadata';
export type StorageTier = 'hot' | 'warm' | 'cold' | 'cloud';

export interface MockDirectoryConfig {
  id: string;
  path: string;
  setupType: SetupType;
  minSpaceGb: number;
  store: boolean;
  scanExisting: boolean;
  overflow: boolean;
  estimatedFiles: number;
  usedBytes: number;
}

export interface MockStagingDirectory {
  id: string;
  path: string;
  usage: ('downloads' | 'merge' | 'drm')[];
  policy: ('drm_only')[];
}

export interface MockDrive {
  id: string;
  name: string;
  path: string;
  device: string;
  backendId: string;
  health: DriveHealthState;
  totalBytes: number;
  usedBytes: number;
  freeBytes: number;
  percentUsed: number;
  fsType: string;
  mountOptions: string;
  tier: StorageTier;
  iops: string;
  latencyMs: number;
  temperatureC?: number;
  isAvailable: boolean;
  directories: MockDirectoryConfig[];
}

export interface MockGlobalStorageSettings {
  downloadDirFormat: string;
  downloadAltDirectoryFormats: string[];
  downloadFilenameFormat: string;
  downloadTextLength: number;
  downloadDateFormat: string;
  downloadOverwrite: boolean;
  metadataDirFormat: string;
  stagingDirectories: MockStagingDirectory[];
}

export interface MockWorkerPropagation {
  status: 'acknowledged' | 'pending' | 'warning';
  targetBackendId: string;
  configVersion: number;
  revision: string;
  lastSyncTime: string;
  message: string;
}

export interface BenchmarkResult {
  readSpeedMb: number;
  writeSpeedMb: number;
  iops: number;
  latencyMs: number;
  timestamp: string;
}

export interface IngestionSimulationResult {
  targetDrive: MockDrive;
  targetDirectory: MockDirectoryConfig;
  resolvedPath: string;
  stagingPath: string;
  overflowTriggered: boolean;
  stepLog: string[];
}

const INITIAL_DRIVES: MockDrive[] = [
  {
    id: 'nvme-fast',
    name: 'NVMe Fast Cache',
    path: '/mnt/storage_fast',
    device: '/dev/nvme0n1p2 (Samsung 990 PRO 2TB)',
    backendId: 'backend_local',
    health: 'healthy',
    totalBytes: 2_000_398_934_016, // ~2.0 TB
    usedBytes: 1_324_567_890_123,  // ~1.32 TB
    freeBytes: 675_831_043_893,   // ~675.8 GB
    percentUsed: 66.2,
    fsType: 'ext4',
    mountOptions: 'rw,noatime,discard,commit=60',
    tier: 'hot',
    iops: '185k IOPS',
    latencyMs: 0.4,
    temperatureC: 41,
    isAvailable: true,
    directories: [
      {
        id: 'dir-fast-dl',
        path: '/mnt/storage_fast/downloads/active',
        setupType: 'download',
        minSpaceGb: 50,
        store: true,
        scanExisting: true,
        overflow: false,
        estimatedFiles: 142_890,
        usedBytes: 1_120_000_000_000,
      },
      {
        id: 'dir-fast-meta',
        path: '/mnt/storage_fast/metadata/primary',
        setupType: 'metadata',
        minSpaceGb: 10,
        store: true,
        scanExisting: false,
        overflow: false,
        estimatedFiles: 84_120,
        usedBytes: 204_567_890_123,
      },
    ],
  },
  {
    id: 'archive-pool',
    name: 'Bulk Archive Pool',
    path: '/media/archive_pool',
    device: '/dev/mapper/zfs-pool-data (8x 16TB RAID-Z2)',
    backendId: 'backend_local',
    health: 'warning',
    totalBytes: 96_000_000_000_000, // 96.0 TB
    usedBytes: 84_480_000_000_000,  // 84.48 TB
    freeBytes: 11_520_000_000_000,  // 11.52 TB
    percentUsed: 88.0,
    fsType: 'zfs',
    mountOptions: 'rw,xattr,noatime,compression=zstd,recordsize=1M',
    tier: 'cold',
    iops: '4.2k IOPS',
    latencyMs: 14.8,
    temperatureC: 36,
    isAvailable: true,
    directories: [
      {
        id: 'dir-arc-media',
        path: '/media/archive_pool/bulk_media',
        setupType: 'download',
        minSpaceGb: 500,
        store: true,
        scanExisting: true,
        overflow: true,
        estimatedFiles: 2_410_500,
        usedBytes: 81_200_000_000_000,
      },
      {
        id: 'dir-arc-meta',
        path: '/media/archive_pool/cold_snapshots',
        setupType: 'metadata',
        minSpaceGb: 100,
        store: false,
        scanExisting: false,
        overflow: false,
        estimatedFiles: 620_000,
        usedBytes: 3_280_000_000_000,
      },
    ],
  },
  {
    id: 'worker-frankfurt',
    name: 'Frankfurt Satellite Mount',
    path: '/mnt/worker_frankfurt',
    device: 'nfs4://10.140.0.12/exports/usv_staging',
    backendId: 'node_worker_frankfurt',
    health: 'critical',
    totalBytes: 4_000_000_000_000, // 4.0 TB
    usedBytes: 3_792_000_000_000,  // 3.79 TB
    freeBytes: 208_000_000_000,    // 208 GB
    percentUsed: 94.8,
    fsType: 'nfs4',
    mountOptions: 'rw,sync,hard,intr,rsize=1048576,wsize=1048576',
    tier: 'warm',
    iops: '1.8k IOPS',
    latencyMs: 32.1,
    isAvailable: true,
    directories: [
      {
        id: 'dir-frank-scratch',
        path: '/mnt/worker_frankfurt/scratch_queue',
        setupType: 'download',
        minSpaceGb: 250,
        store: true,
        scanExisting: false,
        overflow: true,
        estimatedFiles: 389_400,
        usedBytes: 3_792_000_000_000,
      },
    ],
  },
  {
    id: 'cloud-cache',
    name: 'Wasabi Object Vault',
    path: '/data/cloud_cache',
    device: 'rclone:s3_wasabi_vault:usv-cold',
    backendId: 'backend_local',
    health: 'healthy',
    totalBytes: 10_000_000_000_000, // 10.0 TB
    usedBytes: 2_150_000_000_000,  // 2.15 TB
    freeBytes: 7_850_000_000_000,  // 7.85 TB
    percentUsed: 21.5,
    fsType: 'fuse.rclone',
    mountOptions: 'vfs-cache-mode=full,vfs-cache-max-age=48h,dir-cache-time=72h',
    tier: 'cloud',
    iops: '620 IOPS',
    latencyMs: 85.0,
    isAvailable: true,
    directories: [
      {
        id: 'dir-cloud-mirror',
        path: '/data/cloud_cache/mirror',
        setupType: 'download',
        minSpaceGb: 20,
        store: false,
        scanExisting: true,
        overflow: true,
        estimatedFiles: 180_000,
        usedBytes: 2_150_000_000_000,
      },
    ],
  },
  {
    id: 'offline-hdd',
    name: 'Disconnected Expansion HDD',
    path: '/mnt/offline_hdd',
    device: '/dev/sdc1 (Mount Unreachable)',
    backendId: 'backend_local',
    health: 'offline',
    totalBytes: 0,
    usedBytes: 0,
    freeBytes: 0,
    percentUsed: 0,
    fsType: 'unknown (unmounted)',
    mountOptions: 'unmounted',
    tier: 'cold',
    iops: 'N/A',
    latencyMs: 0,
    isAvailable: false,
    directories: [
      {
        id: 'dir-off-legacy',
        path: '/mnt/offline_hdd/legacy_archive',
        setupType: 'download',
        minSpaceGb: 50,
        store: true,
        scanExisting: true,
        overflow: false,
        estimatedFiles: 0,
        usedBytes: 0,
      },
    ],
  },
];

const INITIAL_SETTINGS: MockGlobalStorageSettings = {
  downloadDirFormat: '{site_name}/{first_username_letter}/{user_username}/{content_type}/{media_type}',
  downloadAltDirectoryFormats: [
    '{site_name} Vault/{first_username_letter}/{user_username}/{content_type}/{media_type}',
    '{site_name}/{user_username}/Archived',
  ],
  downloadFilenameFormat: '{filename}_{media_id}.{ext}',
  downloadTextLength: 255,
  downloadDateFormat: 'YYYY-MM-DD',
  downloadOverwrite: false,
  metadataDirFormat: '{site_name}/{first_username_letter}/{user_username}/Metadata',
  stagingDirectories: [
    {
      id: 'stg-1',
      path: '/mnt/storage_fast/staging/downloads',
      usage: ['downloads', 'drm', 'merge'],
      policy: [],
    },
    {
      id: 'stg-2',
      path: '/mnt/storage_fast/staging/drm_quarantine',
      usage: ['drm'],
      policy: ['drm_only'],
    },
  ],
};

const SAMPLE_CREATOR = {
  site_name: 'OnlyFans',
  user_username: 'belle_delphine',
  first_username_letter: 'b',
};

const SAMPLE_POST = {
  content_type: 'Posts',
  media_type: 'Images',
  filename: 'IMG_4920',
  ext: 'jpg',
  post_id: '92847102',
  media_id: '38194012',
  date: '2026-10-18',
};

export function useDrivesMockModel() {
  const [drives, setDrives] = useState<MockDrive[]>(INITIAL_DRIVES);
  const [selectedDriveId, setSelectedDriveId] = useState<string>(INITIAL_DRIVES[0].id);
  const [settings, setSettings] = useState<MockGlobalStorageSettings>(INITIAL_SETTINGS);
  const [modalOpen, setModalOpen] = useState(true);
  const [presentationMode, setPresentationMode] = useState<'modal' | 'workbench'>('modal');
  const [benchmarkResult, setBenchmarkResult] = useState<BenchmarkResult | null>(null);
  const [isBenchmarking, setIsBenchmarking] = useState(false);
  const [selectedDirectoryId, setSelectedDirectoryId] = useState<string>('dir-fast-dl');
  const [notification, setNotification] = useState<{ type: 'success' | 'warning' | 'error'; message: string } | null>(null);

  const [workerPropagation, setWorkerPropagation] = useState<MockWorkerPropagation>({
    status: 'acknowledged',
    targetBackendId: 'backend_local',
    configVersion: 14,
    revision: 'rev-819',
    lastSyncTime: 'Just now',
    message: 'Worker confirmed active storage topology',
  });

  const selectedDrive = useMemo(
    () => drives.find((d) => d.id === selectedDriveId) ?? drives[0],
    [drives, selectedDriveId]
  );

  const selectedDirectory = useMemo(() => {
    for (const drive of drives) {
      const match = drive.directories.find((dir) => dir.id === selectedDirectoryId);
      if (match) return match;
    }
    return selectedDrive.directories[0] ?? null;
  }, [drives, selectedDirectoryId, selectedDrive]);

  // Flash toast notification helper
  const notify = (type: 'success' | 'warning' | 'error', message: string) => {
    setNotification({ type, message });
    setTimeout(() => {
      setNotification((curr) => (curr?.message === message ? null : curr));
    }, 3800);
  };

  // Update a single directory's configuration
  const updateDirectoryConfig = (
    driveId: string,
    dirId: string,
    patch: Partial<MockDirectoryConfig>
  ) => {
    setDrives((prevDrives) =>
      prevDrives.map((drive) => {
        if (drive.id !== driveId) return drive;
        return {
          ...drive,
          directories: drive.directories.map((dir) =>
            dir.id === dirId ? { ...dir, ...patch } : dir
          ),
        };
      })
    );
    notify('success', `Directory settings updated & queued for worker acknowledgment`);
  };

  // Add a new directory to a drive
  const addDirectory = (
    driveId: string,
    newDir: {
      path: string;
      setupType: SetupType;
      minSpaceGb?: number;
      store?: boolean;
      scanExisting?: boolean;
      overflow?: boolean;
    }
  ) => {
    const drive = drives.find((d) => d.id === driveId);
    if (!drive) return;
    if (!drive.isAvailable) {
      notify('error', 'Cannot add directories to an unavailable/offline mount');
      return;
    }

    const trimmedPath = newDir.path.trim();
    if (!trimmedPath) {
      notify('warning', 'Directory path cannot be empty');
      return;
    }

    const created: MockDirectoryConfig = {
      id: `dir-${Date.now()}`,
      path: trimmedPath,
      setupType: newDir.setupType,
      minSpaceGb: newDir.minSpaceGb ?? 20,
      store: newDir.store ?? true,
      scanExisting: newDir.scanExisting ?? true,
      overflow: newDir.overflow ?? false,
      estimatedFiles: 0,
      usedBytes: 0,
    };

    setDrives((prev) =>
      prev.map((d) => (d.id === driveId ? { ...d, directories: [...d.directories, created] } : d))
    );
    setSelectedDirectoryId(created.id);
    notify('success', `Added directory "${trimmedPath}" as ${newDir.setupType}`);
  };

  // Remove a directory from config
  const removeDirectory = (driveId: string, dirId: string) => {
    const drive = drives.find((d) => d.id === driveId);
    const targetDir = drive?.directories.find((dir) => dir.id === dirId);

    setDrives((prev) =>
      prev.map((d) =>
        d.id === driveId
          ? { ...d, directories: d.directories.filter((dir) => dir.id !== dirId) }
          : d
      )
    );

    if (selectedDirectoryId === dirId) {
      setSelectedDirectoryId(drive?.directories[0]?.id ?? '');
    }

    notify(
      'success',
      `Removed "${targetDir?.path ?? dirId}" from configuration (disk files preserved)`
    );
  };

  // Update global formatting settings
  const updateSettings = (patch: Partial<MockGlobalStorageSettings>) => {
    setSettings((prev) => ({ ...prev, ...patch }));
    notify('success', 'Storage routing rules saved & propagated');
  };

  // Token path resolver
  const resolveTokenString = (
    template: string,
    vars: Record<string, string | number> = { ...SAMPLE_CREATOR, ...SAMPLE_POST }
  ) => {
    let result = template;
    for (const [key, val] of Object.entries(vars)) {
      result = result.replace(new RegExp(`\\{${key}\\}`, 'g'), String(val));
    }
    return result;
  };

  // Live resolved paths for display
  const resolvedSample = useMemo(() => {
    const dirSubpath = resolveTokenString(settings.downloadDirFormat);
    const filename = resolveTokenString(settings.downloadFilenameFormat);
    const metaSubpath = resolveTokenString(settings.metadataDirFormat);

    const primaryDir = selectedDrive.directories.find((d) => d.setupType === 'download' && d.store);
    const activeBasePath = primaryDir ? primaryDir.path : selectedDrive.path;

    return {
      downloadSubpath: dirSubpath,
      downloadFilename: filename,
      downloadFullPath: `${activeBasePath}/${dirSubpath}/${filename}`.replace(/\/+/g, '/'),
      metadataSubpath: metaSubpath,
      metadataFullPath: `${activeBasePath}/${metaSubpath}/user_profile.json`.replace(/\/+/g, '/'),
      altPaths: settings.downloadAltDirectoryFormats.map((alt) =>
        `${activeBasePath}/${resolveTokenString(alt)}/${filename}`.replace(/\/+/g, '/')
      ),
    };
  }, [settings, selectedDrive]);

  // Run benchmark simulation
  const runBenchmark = () => {
    if (!selectedDrive.isAvailable) {
      notify('error', 'Cannot run benchmark on offline mount');
      return;
    }
    setIsBenchmarking(true);
    setTimeout(() => {
      let readMb = 3450;
      let writeMb = 2890;
      let iops = 192000;
      let latency = 0.38;

      if (selectedDrive.id === 'archive-pool') {
        readMb = 480;
        writeMb = 310;
        iops = 4800;
        latency = 13.2;
      } else if (selectedDrive.id === 'worker-frankfurt') {
        readMb = 112;
        writeMb = 94;
        iops = 1950;
        latency = 28.5;
      } else if (selectedDrive.id === 'cloud-cache') {
        readMb = 65;
        writeMb = 42;
        iops = 650;
        latency = 79.4;
      }

      setBenchmarkResult({
        readSpeedMb: readMb,
        writeSpeedMb: writeMb,
        iops,
        latencyMs: latency,
        timestamp: new Date().toLocaleTimeString(),
      });
      setIsBenchmarking(false);
      notify('success', `I/O benchmark completed for ${selectedDrive.name}`);
    }, 1200);
  };

  // Simulate ingestion flow
  const simulateIngestion = (freeSpaceOverrideGb?: number): IngestionSimulationResult => {
    const currentFreeGb =
      freeSpaceOverrideGb !== undefined
        ? freeSpaceOverrideGb
        : selectedDrive.freeBytes / (1024 * 1024 * 1024);

    const logs: string[] = [];
    logs.push(`[1] Ingestion triggered: ${SAMPLE_CREATOR.site_name} / @${SAMPLE_CREATOR.user_username}`);
    logs.push(`[2] Staging allocated: ${settings.stagingDirectories[0]?.path ?? '/tmp'}`);

    const primaryDownloadDir = selectedDrive.directories.find(
      (dir) => dir.setupType === 'download' && dir.store
    );

    let targetDrive = selectedDrive;
    let targetDir = primaryDownloadDir ?? selectedDrive.directories[0];
    let overflowTriggered = false;

    if (!targetDir || !selectedDrive.isAvailable || currentFreeGb < (targetDir?.minSpaceGb ?? 0)) {
      logs.push(
        `[3] Threshold barrier reached! Mount free space (${currentFreeGb.toFixed(1)} GB) is below minimum threshold (${targetDir?.minSpaceGb ?? 0} GB).`
      );

      // Find overflow drive
      const overflowCandidate = drives
        .filter((d) => d.isAvailable && d.id !== selectedDrive.id)
        .find((d) => d.directories.some((dir) => dir.overflow && dir.store));

      if (overflowCandidate) {
        targetDrive = overflowCandidate;
        targetDir = overflowCandidate.directories.find((dir) => dir.overflow && dir.store)!;
        overflowTriggered = true;
        logs.push(
          `[4] Overflow routing active! Redirecting to spillway mount: ${overflowCandidate.path} (${targetDir.path})`
        );
      } else {
        logs.push(`[4] Warning: No overflow mounts with available storage configured! Ingestion paused.`);
      }
    } else {
      logs.push(`[3] Free space check passed (${currentFreeGb.toFixed(1)} GB free >= ${targetDir.minSpaceGb} GB min).`);
      logs.push(`[4] Routing to canonical primary download directory: ${targetDir.path}`);
    }

    const subpath = resolveTokenString(settings.downloadDirFormat);
    const fname = resolveTokenString(settings.downloadFilenameFormat);
    const resolvedPath = `${targetDir?.path ?? ''}/${subpath}/${fname}`.replace(/\/+/g, '/');

    logs.push(`[5] Final resolved destination: ${resolvedPath}`);

    return {
      targetDrive,
      targetDirectory: targetDir,
      resolvedPath,
      stagingPath: `${settings.stagingDirectories[0]?.path ?? '/tmp/staging'}/staging_${SAMPLE_POST.media_id}.part`,
      overflowTriggered,
      stepLog: logs,
    };
  };

  // Factory reset
  const reset = () => {
    setDrives(INITIAL_DRIVES);
    setSelectedDriveId(INITIAL_DRIVES[0].id);
    setSelectedDirectoryId('dir-fast-dl');
    setSettings(INITIAL_SETTINGS);
    setBenchmarkResult(null);
    setWorkerPropagation({
      status: 'acknowledged',
      targetBackendId: 'backend_local',
      configVersion: 14,
      revision: 'rev-819',
      lastSyncTime: 'Just now',
      message: 'Worker confirmed active storage topology',
    });
    notify('success', 'Drive mock model reset to initial states');
  };

  return {
    drives,
    selectedDrive,
    selectedDriveId,
    setSelectedDriveId,
    selectedDirectory,
    selectedDirectoryId,
    setSelectedDirectoryId,
    settings,
    modalOpen,
    setModalOpen,
    presentationMode,
    setPresentationMode,
    benchmarkResult,
    isBenchmarking,
    notification,
    workerPropagation,
    resolvedSample,
    updateDirectoryConfig,
    addDirectory,
    removeDirectory,
    updateSettings,
    runBenchmark,
    simulateIngestion,
    resolveTokenString,
    reset,
  };
}

export type DrivesMockModel = ReturnType<typeof useDrivesMockModel>;
