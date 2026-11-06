/**
 * Copies text to the clipboard.
 *
 * Browsers only offer navigator.clipboard on secure pages (HTTPS or localhost),
 * so a WebUI opened at http://<server-address> has none. There this falls back
 * to selecting the text in a hidden textarea and copying it, which still works
 * in response to a click.
 */
export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  // Off screen, so selecting it neither scrolls nor flashes the page.
  area.style.position = 'fixed';
  area.style.top = '-1000px';
  area.style.opacity = '0';
  document.body.appendChild(area);
  const focused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  try {
    area.focus();
    area.select();
    // execCommand is deprecated but remains the only copy without a secure page.
    if (!document.execCommand('copy')) throw new Error('This browser did not allow copying.');
  } finally {
    area.remove();
    focused?.focus();
  }
}
