import { fireEvent, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type Player from 'video.js/dist/types/player';

import { VideoPlayer } from '../../src/components/VideoPlayer';
import { renderWithProviders } from './testUtils';

describe('VideoPlayer keyboard shortcuts and scrubbing', () => {
  it('scrubs to correct percentage when number keys 0-9 are pressed on focused player', async () => {
    let playerInstance: Player | null = null;

    renderWithProviders(
      <VideoPlayer
        src="http://localhost:3000/api/v1/media/stream/onlyfans/1"
        onReady={(player) => {
          playerInstance = player;
        }}
      />
    );

    await waitFor(() => {
      expect(playerInstance).not.toBeNull();
    });

    const player = playerInstance as unknown as Player;

    let currentTime = 10;
    vi.spyOn(player, 'duration').mockReturnValue(120);
    vi.spyOn(player, 'currentTime').mockImplementation(((time?: number) => {
      if (typeof time === 'number') {
        currentTime = time;
        return player;
      }
      return currentTime;
    }) as unknown as typeof player.currentTime);

    const playerElement = player.el() as HTMLElement;
    expect(playerElement).not.toBeNull();

    // Click to focus player
    fireEvent.click(playerElement);
    playerElement.focus();

    // Press '5' -> 50% of 120s = 60s
    fireEvent.keyDown(playerElement, { key: '5', code: 'Digit5' });
    expect(currentTime).toBe(60);

    // Press '0' -> 0% of 120s = 0s
    fireEvent.keyDown(playerElement, { key: '0', code: 'Digit0' });
    expect(currentTime).toBe(0);

    // Press '9' -> 90% of 120s = 108s
    fireEvent.keyDown(playerElement, { key: '9', code: 'Digit9' });
    expect(currentTime).toBe(108);

    // Press '3' -> 30% of 120s = 36s
    fireEvent.keyDown(playerElement, { key: '3', code: 'Digit3' });
    expect(currentTime).toBe(36);
  });

  it('handles arrow, j/l seek, home/end, and mute shortcuts', async () => {
    let playerInstance: Player | null = null;

    renderWithProviders(
      <VideoPlayer
        src="http://localhost:3000/api/v1/media/stream/onlyfans/1"
        onReady={(player) => {
          playerInstance = player;
        }}
      />
    );

    await waitFor(() => {
      expect(playerInstance).not.toBeNull();
    });

    const player = playerInstance as unknown as Player;
    let currentTime = 50;
    let volume = 0.8;
    let muted = false;

    vi.spyOn(player, 'duration').mockReturnValue(100);
    vi.spyOn(player, 'currentTime').mockImplementation(((time?: number) => {
      if (typeof time === 'number') {
        currentTime = time;
        return player;
      }
      return currentTime;
    }) as unknown as typeof player.currentTime);

    vi.spyOn(player, 'volume').mockImplementation(((val?: number) => {
      if (typeof val === 'number') {
        volume = val;
        return player;
      }
      return volume;
    }) as unknown as typeof player.volume);

    vi.spyOn(player, 'muted').mockImplementation(((val?: boolean) => {
      if (typeof val === 'boolean') {
        muted = val;
        return player;
      }
      return muted;
    }) as unknown as typeof player.muted);

    const playerElement = player.el() as HTMLElement;
    fireEvent.click(playerElement);
    playerElement.focus();

    // ArrowLeft -> -5s => 45s
    fireEvent.keyDown(playerElement, { key: 'ArrowLeft' });
    expect(currentTime).toBe(45);

    // ArrowRight -> +5s => 50s
    fireEvent.keyDown(playerElement, { key: 'ArrowRight' });
    expect(currentTime).toBe(50);

    // 'j' -> -10s => 40s
    fireEvent.keyDown(playerElement, { key: 'j' });
    expect(currentTime).toBe(40);

    // 'l' -> +10s => 50s
    fireEvent.keyDown(playerElement, { key: 'l' });
    expect(currentTime).toBe(50);

    // 'Home' -> 0s
    fireEvent.keyDown(playerElement, { key: 'Home' });
    expect(currentTime).toBe(0);

    // 'End' -> 100s
    fireEvent.keyDown(playerElement, { key: 'End' });
    expect(currentTime).toBe(100);

    // 'm' -> mute toggle
    fireEvent.keyDown(playerElement, { key: 'm' });
    expect(muted).toBe(true);

    // 'ArrowUp' -> volume + 0.1
    fireEvent.keyDown(playerElement, { key: 'ArrowUp' });
    expect(volume).toBeCloseTo(0.9);
  });
});
