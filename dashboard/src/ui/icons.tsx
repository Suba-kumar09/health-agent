import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement>;
const base = { viewBox: "0 0 24 24", fill: "none", "aria-hidden": true } as const;

export const DotIcon = (p: P) => (
  <svg {...base} {...p}>
    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.4" />
  </svg>
);
export const ClockIcon = (p: P) => (
  <svg {...base} {...p}>
    <path d="M12 7v5l3 3" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.4" />
  </svg>
);
export const AlertIcon = (p: P) => (
  <svg {...base} {...p}>
    <path d="M12 8v5M12 16h.01" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.4" />
  </svg>
);
export const OffIcon = (p: P) => (
  <svg {...base} {...p}>
    <path d="M5 5l14 14M5 19L19 5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
  </svg>
);
export const LockIcon = (p: P) => (
  <svg {...base} {...p}>
    <rect x="5" y="11" width="14" height="9" rx="2" stroke="currentColor" strokeWidth="2.2" />
    <path d="M8 11V8a4 4 0 118 0v3" stroke="currentColor" strokeWidth="2.2" />
  </svg>
);
export const CupIcon = (p: P) => (
  <svg {...base} {...p}>
    <path
      d="M5 10h11v4a5 5 0 01-5 5h-1a5 5 0 01-5-5zM16 11h1.5a2.5 2.5 0 010 5H16M8 3v3M11 3v3"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    />
  </svg>
);
export const ChevronIcon = (p: P) => (
  <svg {...base} {...p}>
    <path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
export const CloseIcon = (p: P) => (
  <svg {...base} {...p}>
    <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
  </svg>
);
export const ShieldIcon = (p: P) => (
  <svg {...base} {...p}>
    <path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z" stroke="currentColor" strokeWidth="2" />
  </svg>
);
export const PointerIcon = (p: P) => (
  <svg {...base} {...p}>
    <path d="M9 3v10l3-3 2 5 2-1-2-5h4z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
  </svg>
);
export const SunIcon = (p: P) => (
  <svg {...base} {...p}>
    <circle cx="12" cy="12" r="4" stroke="currentColor" strokeWidth="2" />
    <path
      d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
    />
  </svg>
);
export const MoonIcon = (p: P) => (
  <svg {...base} {...p}>
    <path d="M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
  </svg>
);
export const LogoutIcon = (p: P) => (
  <svg {...base} {...p}>
    <path
      d="M15 4h3a2 2 0 012 2v12a2 2 0 01-2 2h-3M10 17l5-5-5-5M15 12H4"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export const PulseMark = (p: P) => (
  <svg {...base} {...p}>
    <path d="M3 12h4l2 7 4-14 2 7h6" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
