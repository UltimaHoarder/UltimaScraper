/**
 * HTML sanitization utilities for safe rendering of user content.
 */

import DOMPurify from 'dompurify';

/**
 * Sanitize HTML content for safe rendering.
 * Allows basic formatting tags while stripping dangerous content.
 */
function sanitizeHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS: [
      'p', 'br', 'strong', 'b', 'em', 'i', 'u', 's', 'strike',
      'a', 'span', 'div', 'ul', 'ol', 'li',
    ],
    ALLOWED_ATTR: ['href', 'target', 'rel', 'class'],
    // Open links in new tab for safety
    ADD_ATTR: ['target'],
    FORBID_TAGS: ['script', 'style', 'iframe', 'form', 'input', 'object', 'embed'],
    FORBID_ATTR: ['onclick', 'onerror', 'onload', 'style'],
  });
}

/**
 * Sanitize HTML and add target="_blank" rel="noopener noreferrer" to all links.
 */
export function sanitizeHtmlWithSafeLinks(html: string): string {
  const sanitized = sanitizeHtml(html);

  const temp = document.createElement('div');
  temp.innerHTML = sanitized;

  temp.querySelectorAll('a').forEach(link => {
    link.setAttribute('target', '_blank');
    link.setAttribute('rel', 'noopener noreferrer');
  });

  return temp.innerHTML;
}

/**
 * Strip all HTML tags and return the decoded plain text.
 * Content of script/style elements is dropped rather than surfaced as text.
 */
export function stripHtml(html: string | null | undefined): string {
  if (!html) return '';
  // DOMParser builds an inert document (no script execution or resource loads)
  // and is several times faster than a DOMPurify pass for list rendering.
  const body = new DOMParser().parseFromString(html, 'text/html').body;
  for (const element of body.querySelectorAll('script, style, template, noscript')) {
    element.remove();
  }
  return body.textContent ?? '';
}
