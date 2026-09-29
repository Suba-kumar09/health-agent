import type { MessageKind, SegmentState, Status, WindowItem } from "./types";

export function duration(secs: number): string {
  const mins = Math.round(secs / 60);
  if (mins < 1) return secs > 0 ? "<1m" : "0m";
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (h === 0) return `${m}m`;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

// A length of time in whole or half hours, e.g. 28800 -> "8h", 27000 -> "7.5h".
export function hoursLabel(secs: number): string {
  const h = Math.round((secs / 3600) * 10) / 10;
  return `${h}h`;
}

export function clock(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function ago(ts: number | null, now: number): string {
  if (ts == null) return "never";
  const diff = Math.max(0, now - ts);
  if (diff < 60) return "just now";
  const mins = Math.round(diff / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

export function initials(name: string): string {
  // Letters and digits only, so "QA Admin (temporary)" gives "QT", not "Q(".
  const parts = name.replace(/[^\p{L}\p{N}\s]/gu, " ").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const letters = parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : parts[0].slice(0, 2);
  return letters.toUpperCase();
}

export function weekday(date: string): string {
  return new Date(`${date}T12:00:00`).toLocaleDateString([], { weekday: "short" });
}

export function isWeekend(date: string): boolean {
  const d = new Date(`${date}T12:00:00`).getDay();
  return d === 0 || d === 6;
}

export const STATE_LABEL: Record<SegmentState, string> = {
  active: "Active",
  distraction: "Distraction",
  idle: "Idle",
  locked: "Locked",
};

export const STATUS_LABEL: Record<Status, string> = {
  active: "Active",
  distraction: "Distracted",
  idle: "Idle",
  locked: "Locked",
  offline: "Offline",
  no_device: "No device",
};

export const KIND_LABEL: Record<MessageKind, string> = {
  break: "Break reminder",
  idle: "Idle check-in",
  distraction: "Distraction nudge",
};

// "Chrome · youtube.com" style subtitle for a window row.
export function windowSource(w: WindowItem): string {
  return w.site ? `${w.app} · ${w.site}` : w.app;
}

// Main line for a window; falls back to site/app when titles are hidden from admins.
export function windowTitle(w: WindowItem): string {
  return w.title ?? w.site ?? w.app;
}
