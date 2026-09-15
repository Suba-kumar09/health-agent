import { useState } from "react";
import type { AppUsage } from "../types";
import { formatDuration } from "../format";
import "./AppUsageChart.css";

interface AppUsageChartProps {
  appUsage: AppUsage[];
}

// Evenly spaced hues rather than a fixed palette so any number of apps
// (up to the server's top-8 cap) gets a distinct, theme-agnostic color
// without hardcoding more series tokens into index.css.
function colorFor(index: number, total: number): string {
  const hue = Math.round((360 / Math.max(total, 1)) * index);
  return `hsl(${hue}deg 65% 60%)`;
}

// Circle circumference is normalized to 100 (r=15.915) so each slice's
// stroke-dasharray/-dashoffset can be expressed directly as a percentage --
// the standard SVG "pie from circles" trick. Offset by 25 so the first
// slice starts at 12 o'clock instead of 3 o'clock.
const R = 15.915;

export function AppUsageChart({ appUsage }: AppUsageChartProps) {
  const [hovered, setHovered] = useState<number | null>(null);
  const totalSecs = appUsage.reduce((sum, a) => sum + a.secs, 0);

  if (appUsage.length === 0 || totalSecs === 0) {
    return (
      <div className="app-usage-chart">
        <h2 className="app-usage-chart__title">Most used apps</h2>
        <p className="app-usage-chart__empty">No app activity recorded yet today.</p>
      </div>
    );
  }

  let cumulativePct = 0;
  const slices = appUsage.map((a, i) => {
    const pct = (a.secs / totalSecs) * 100;
    const dashoffset = 25 - cumulativePct;
    cumulativePct += pct;
    return { ...a, pct, dashoffset, color: colorFor(i, appUsage.length) };
  });

  const active = hovered !== null ? slices[hovered] : null;

  return (
    <div className="app-usage-chart">
      <div className="app-usage-chart__header">
        <h2 className="app-usage-chart__title">Most used apps</h2>
        <div className="app-usage-chart__readout">
          {active ? (
            <>
              <strong>{active.app}</strong> &middot; {formatDuration(active.secs)}
            </>
          ) : (
            <span className="app-usage-chart__readout-hint">Hover a slice for details</span>
          )}
        </div>
      </div>
      <div className="app-usage-chart__body">
        <svg
          className="app-usage-chart__donut"
          viewBox="0 0 36 36"
          role="img"
          aria-label="Time spent per application today"
        >
          {slices.map((s, i) => (
            <circle
              key={s.app}
              cx="18"
              cy="18"
              r={R}
              fill="transparent"
              stroke={s.color}
              strokeWidth={hovered === i ? 5 : 4}
              strokeDasharray={`${s.pct} ${100 - s.pct}`}
              strokeDashoffset={s.dashoffset}
              className="app-usage-chart__slice"
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered((h) => (h === i ? null : h))}
            >
              <title>
                {s.app} — {formatDuration(s.secs)}
              </title>
            </circle>
          ))}
        </svg>
        <ul className="app-usage-chart__legend">
          {slices.map((s, i) => (
            <li
              key={s.app}
              className={`app-usage-chart__legend-row${hovered === i ? " app-usage-chart__legend-row--hovered" : ""}`}
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered((h) => (h === i ? null : h))}
              title={`${s.app} — ${formatDuration(s.secs)}`}
            >
              <span className="app-usage-chart__legend-dot" style={{ background: s.color }} />
              <span className="app-usage-chart__legend-name">{s.app}</span>
              <span className="app-usage-chart__legend-time">{formatDuration(s.secs)}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
