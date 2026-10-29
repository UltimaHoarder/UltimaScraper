import type { SVGProps } from 'react';

import type { NavIconName } from './navigation';

function IconFrame({
  children,
  className,
}: {
  children: SVGProps<SVGSVGElement>['children'];
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export function NavIcon({ name, className }: { name: NavIconName; className?: string }) {
  switch (name) {
    case 'dashboard':
      return (
        <IconFrame className={className}>
          <rect x="3" y="3" width="7" height="7" rx="1.5" />
          <rect x="14" y="3" width="7" height="4" rx="1.5" />
          <rect x="14" y="10" width="7" height="11" rx="1.5" />
          <rect x="3" y="13" width="7" height="8" rx="1.5" />
        </IconFrame>
      );
    case 'statistics':
      return (
        <IconFrame className={className}>
          <path d="M4 19V5" />
          <path d="M4 19h16" />
          <path d="m7 15 4-4 3 2 5-6" />
        </IconFrame>
      );
    case 'logs':
      return (
        <IconFrame className={className}>
          <path d="M8 6h10" />
          <path d="M8 12h10" />
          <path d="M8 18h10" />
          <path d="M4 6h.01" />
          <path d="M4 12h.01" />
          <path d="M4 18h.01" />
        </IconFrame>
      );
    case 'jobs':
      return (
        <IconFrame className={className}>
          <rect x="4" y="5" width="16" height="4" rx="1.5" />
          <rect x="4" y="10" width="16" height="4" rx="1.5" />
          <rect x="4" y="15" width="16" height="4" rx="1.5" />
        </IconFrame>
      );
    case 'search':
      return (
        <IconFrame className={className}>
          <circle cx="11" cy="11" r="6" />
          <path d="m20 20-3.5-3.5" />
        </IconFrame>
      );
    case 'orders':
      return (
        <IconFrame className={className}>
          <path d="M7 4h10l2 3v13H5V7l2-3Z" />
          <path d="M9 11h6" />
          <path d="M9 15h4" />
        </IconFrame>
      );
    case 'tools':
      return (
        <IconFrame className={className}>
          <path d="m14 7 3-3 3 3-3 3" />
          <path d="M4 20 14 10" />
          <path d="m8 4 4 4" />
        </IconFrame>
      );
    case 'scraper':
      return (
        <IconFrame className={className}>
          <path d="M12 3 8 11l4 2 4-2-4-8Z" />
          <path d="M8 11 5 20h14l-3-9" />
        </IconFrame>
      );
    case 'content':
      return (
        <IconFrame className={className}>
          <path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 0-3 3Z" />
          <path d="M5 4v16a3 3 0 0 1 3-3h11" />
        </IconFrame>
      );
    case 'media':
      return (
        <IconFrame className={className}>
          <rect x="3" y="5" width="18" height="14" rx="2" />
          <circle cx="9" cy="10" r="1.5" />
          <path d="m21 15-5-5-7 7" />
        </IconFrame>
      );
    case 'favourites':
      return (
        <IconFrame className={className}>
          <path d="m12 4 2.4 4.9 5.4.8-3.9 3.8.9 5.4-4.8-2.5-4.8 2.5.9-5.4-3.9-3.8 5.4-.8Z" />
        </IconFrame>
      );
    case 'users':
      return (
        <IconFrame className={className}>
          <circle cx="9" cy="8" r="3" />
          <path d="M4 19a5 5 0 0 1 10 0" />
          <circle cx="17" cy="9" r="2.5" />
          <path d="M15 19a4 4 0 0 1 5 0" />
        </IconFrame>
      );
    case 'subscriptions':
      return (
        <IconFrame className={className}>
          <path d="M4 7h16v10H4z" />
          <path d="m4 8 8 6 8-6" />
        </IconFrame>
      );
    case 'chats':
      return (
        <IconFrame className={className}>
          <path d="M5 6h14v9H9l-4 4V6Z" />
          <path d="M9 10h6" />
        </IconFrame>
      );
    case 'auths':
      return (
        <IconFrame className={className}>
          <rect x="5" y="11" width="14" height="9" rx="2" />
          <path d="M8 11V8a4 4 0 1 1 8 0v3" />
        </IconFrame>
      );
    case 'system':
      return (
        <IconFrame className={className}>
          <rect x="4" y="5" width="16" height="10" rx="2" />
          <path d="M8 19h8" />
          <path d="M12 15v4" />
        </IconFrame>
      );
    case 'network':
      return (
        <IconFrame className={className}>
          <circle cx="12" cy="12" r="8" />
          <path d="M4 12h16" />
          <path d="M12 4a12 12 0 0 1 0 16" />
          <path d="M12 4a12 12 0 0 0 0 16" />
        </IconFrame>
      );
    case 'database':
      return (
        <IconFrame className={className}>
          <ellipse cx="12" cy="6" rx="7" ry="3" />
          <path d="M5 6v8c0 1.7 3.1 3 7 3s7-1.3 7-3V6" />
          <path d="M5 10c0 1.7 3.1 3 7 3s7-1.3 7-3" />
        </IconFrame>
      );
    case 'webhooks':
      return (
        <IconFrame className={className}>
          <path d="M8 8a3 3 0 0 1 5-2l1 1" />
          <path d="M16 16a3 3 0 0 1-5 2l-1-1" />
          <path d="M10 14 14 10" />
          <path d="M7 17a3 3 0 1 1 0-6" />
          <path d="M17 13a3 3 0 1 1 0-6" />
        </IconFrame>
      );
    case 'settings':
      return (
        <IconFrame className={className}>
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1 1 0 0 0 .2 1.1l.1.1a1 1 0 0 1 0 1.4l-1.2 1.2a1 1 0 0 1-1.4 0l-.1-.1a1 1 0 0 0-1.1-.2 1 1 0 0 0-.6.9V20a1 1 0 0 1-1 1h-1.8a1 1 0 0 1-1-1v-.2a1 1 0 0 0-.6-.9 1 1 0 0 0-1.1.2l-.1.1a1 1 0 0 1-1.4 0l-1.2-1.2a1 1 0 0 1 0-1.4l.1-.1a1 1 0 0 0 .2-1.1 1 1 0 0 0-.9-.6H4a1 1 0 0 1-1-1v-1.8a1 1 0 0 1 1-1h.2a1 1 0 0 0 .9-.6 1 1 0 0 0-.2-1.1l-.1-.1a1 1 0 0 1 0-1.4l1.2-1.2a1 1 0 0 1 1.4 0l.1.1a1 1 0 0 0 1.1.2 1 1 0 0 0 .6-.9V4a1 1 0 0 1 1-1h1.8a1 1 0 0 1 1 1v.2a1 1 0 0 0 .6.9 1 1 0 0 0 1.1-.2l.1-.1a1 1 0 0 1 1.4 0l1.2 1.2a1 1 0 0 1 0 1.4l-.1.1a1 1 0 0 0-.2 1.1 1 1 0 0 0 .9.6h.2a1 1 0 0 1 1 1V13a1 1 0 0 1-1 1h-.2a1 1 0 0 0-.9.6Z" />
        </IconFrame>
      );
    case 'bolt':
      return (
        <IconFrame className={className}>
          <path d="M13 2 5 13h5l-1 9 8-11h-5l1-9Z" />
        </IconFrame>
      );
  }
}
