export function formatDuration(seconds: number): string {
  const mins = Math.round(seconds / 60);
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

export function formatClock(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatHeaderDate(date: Date): { day: string; time: string } {
  return {
    day: date.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric" }),
    time: date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }),
  };
}

export function formatRelativeTime(ts: number, now: number): string {
  const diff = Math.max(0, now - ts);
  if (diff < 60) return "just now";
  const mins = Math.round(diff / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  return `${hours}h ago`;
}
