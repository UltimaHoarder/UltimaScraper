import { readStorage, writeStorage } from '../shared/lib/browserStorage';

const STORAGE_KEY_VOLUME = 'usr_video_player_volume';
const STORAGE_KEY_MUTED = 'usr_video_player_muted';

// Keeps the last choice for this page session when storage is unavailable.
let memoryVolume: number | null = null;
let memoryMuted: boolean | null = null;

export function getPersistedVolume(): number | null {
  const value = readStorage(STORAGE_KEY_VOLUME);
  if (value !== null) {
    const parsed = Number.parseFloat(value);
    if (!Number.isNaN(parsed) && parsed >= 0 && parsed <= 1) {
      return parsed;
    }
  }
  return memoryVolume;
}

export function setPersistedVolume(volume: number): void {
  const clamped = Math.max(0, Math.min(1, volume));
  memoryVolume = clamped;
  writeStorage(STORAGE_KEY_VOLUME, clamped.toString());
}

export function getPersistedMuted(): boolean | null {
  const value = readStorage(STORAGE_KEY_MUTED);
  if (value !== null) {
    return value === 'true';
  }
  return memoryMuted;
}

export function setPersistedMuted(muted: boolean): void {
  memoryMuted = muted;
  writeStorage(STORAGE_KEY_MUTED, muted.toString());
}
