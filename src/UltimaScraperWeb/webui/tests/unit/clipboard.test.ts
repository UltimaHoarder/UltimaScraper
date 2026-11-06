import { afterEach, describe, expect, it, vi } from 'vitest';

import { copyText } from '../../src/utils/clipboard';

const original = Object.getOwnPropertyDescriptor(navigator, 'clipboard');

afterEach(() => {
  if (original) Object.defineProperty(navigator, 'clipboard', original);
  else Reflect.deleteProperty(navigator, 'clipboard');
  vi.restoreAllMocks();
});

function setClipboard(value: Clipboard | undefined) {
  Object.defineProperty(navigator, 'clipboard', { value, configurable: true });
}

describe('copyText', () => {
  it('uses the Clipboard API on a secure page', async () => {
    const writeText = vi.fn(async () => undefined);
    setClipboard({ writeText } as unknown as Clipboard);

    await copyText('usr://cluster/abc');

    expect(writeText).toHaveBeenCalledWith('usr://cluster/abc');
  });

  it('copies through a hidden textarea when the page is plain HTTP', async () => {
    // http://<server-address> has no navigator.clipboard.
    setClipboard(undefined);
    const copied: string[] = [];
    const execCommand = vi.fn((command: string) => {
      copied.push(`${command}:${(document.activeElement as HTMLTextAreaElement).value}`);
      return true;
    });
    Object.defineProperty(document, 'execCommand', { value: execCommand, configurable: true });

    await copyText('usr://cluster/abc');

    expect(copied).toEqual(['copy:usr://cluster/abc']);
    // The textarea is gone again.
    expect(document.querySelector('textarea')).toBeNull();
  });

  it('says so when the browser refuses to copy', async () => {
    setClipboard(undefined);
    Object.defineProperty(document, 'execCommand', { value: vi.fn(() => false), configurable: true });

    await expect(copyText('usr://cluster/abc')).rejects.toThrow('did not allow copying');
  });
});
