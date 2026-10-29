export function AtlasMark({ className = '' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 64 48" fill="currentColor" aria-hidden="true">
      <path d="M0 48 24 0h16l24 48H46L32 18 18 48Z" />
      <path d="M25 37h14l5 11H20Z" />
    </svg>
  );
}
