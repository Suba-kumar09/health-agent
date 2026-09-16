// Small hand-rolled icon set (no icon library dependency, matching this
// project's existing no-chart-library convention).
interface IconProps {
  size?: number;
}

function common(size = 16) {
  return { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor" } as const;
}

export function FlameIcon({ size }: IconProps = {}) {
  return (
    <svg {...common(size)} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2c1 3-2 4-2 7a4 4 0 0 0 8 0c0-1-.5-2-1-2 .5 2-.5 3-1.5 3-1.5 0-2-1.5-1-3-2 1-4 3-4 6a5.5 5.5 0 0 0 11 0c0-4-3-6-4-9-.5 1.5-.5 2.5 0 3-2-1-3-3-3-5Z" />
    </svg>
  );
}

export function KeyboardIcon({ size }: IconProps = {}) {
  return (
    <svg {...common(size)} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="6" width="20" height="12" rx="2" />
      <path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M6 14h12" />
    </svg>
  );
}

export function MoonIcon({ size }: IconProps = {}) {
  return (
    <svg {...common(size)} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z" />
    </svg>
  );
}

export function LockIcon({ size }: IconProps = {}) {
  return (
    <svg {...common(size)} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <rect x="4" y="11" width="16" height="9" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </svg>
  );
}

export function SigmaIcon({ size }: IconProps = {}) {
  return (
    <svg {...common(size)} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 4H6l6 8-6 8h12" />
    </svg>
  );
}

export function HomeIcon({ size }: IconProps = {}) {
  return (
    <svg {...common(size)} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 11.5 12 4l9 7.5" />
      <path d="M5 10v9a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1v-9" />
    </svg>
  );
}

export function HistoryIcon({ size }: IconProps = {}) {
  return (
    <svg {...common(size)} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="13" r="8" />
      <path d="M12 9v4l3 2" />
      <path d="M9 2h6" />
    </svg>
  );
}

export function TargetIcon({ size }: IconProps = {}) {
  return (
    <svg {...common(size)} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="12" cy="12" r="0.5" fill="currentColor" />
    </svg>
  );
}

export function GearIcon({ size }: IconProps = {}) {
  return (
    <svg {...common(size)} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
    </svg>
  );
}

export function BellIcon({ size }: IconProps = {}) {
  return (
    <svg {...common(size)} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 8a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6" />
      <path d="M10 20a2 2 0 0 0 4 0" />
    </svg>
  );
}

export function SunIcon({ size }: IconProps = {}) {
  return (
    <svg {...common(size)} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}

export function GridIcon({ size }: IconProps = {}) {
  return (
    <svg {...common(size)} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
    </svg>
  );
}

export function UserIcon({ size }: IconProps = {}) {
  return (
    <svg {...common(size)} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="8" r="4" />
      <path d="M4 20c0-4 4-6 8-6s8 2 8 6" />
    </svg>
  );
}

export function ChevronRightIcon({ size }: IconProps = {}) {
  return (
    <svg {...common(size)} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="m9 6 6 6-6 6" />
    </svg>
  );
}
