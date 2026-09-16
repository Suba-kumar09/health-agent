import { useState } from "react";
import type { AppUsage, NudgeMessage } from "../types";
import { formatDuration, formatRelativeTime } from "../format";
import { GridIcon } from "./icons";
import "./AppUsageChart.css";

interface AppUsageChartProps {
  appUsage: AppUsage[];
  messages: NudgeMessage[];
  now: number;
}

// A curated, harmonious set (rather than raw evenly-spaced hue rotation,
// which produces muddy/clashing colors at fixed saturation+lightness) --
// ordered so the biggest slice (index 0, since the server already sorts
// app_usage descending) always gets the same reliable, vivid teal, with
// the rest reading as a coherent set rather than a rainbow. Falls back to
// hue rotation only past the server's top-8 cap, which is never expected.
const PALETTE = ["#5fd0c0", "#3987e5", "#ecb531", "#d95926", "#8b7fe8", "#e8598a", "#63c368", "#a1a8b3"];

function colorFor(index: number, total: number): string {
  if (index < PALETTE.length) return PALETTE[index];
  const hue = Math.round((360 / Math.max(total, 1)) * index);
  return `hsl(${hue}deg 60% 60%)`;
}

// Circle circumference is normalized to 100 (r=15.915) so each slice's
// stroke-dasharray/-dashoffset can be expressed directly as a percentage --
// the standard SVG "pie from circles" trick. Offset by 25 so the first
// slice starts at 12 o'clock instead of 3 o'clock.
const R = 15.915;

export function AppUsageChart({ appUsage, messages, now }: AppUsageChartProps) {
  const [hovered, setHovered] = useState<number | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
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
  // dashboard.py's app_usage buckets use the same title-first label
  // precedence as a distraction Message's own `label` (see
  // server/routes/dashboard.py's app_secs comment) -- so a slice's `app`
  // string is expected to equal a distraction message's `label` exactly
  // for the same underlying window/tab, no fuzzy matching needed.
  const selectedMessages = selected
    ? messages.filter((m) => m.kind === "distraction" && m.label === selected)
    : [];

  function toggleSelected(app: string) {
    setSelected((s) => (s === app ? null : app));
  }

  return (
    <div className="app-usage-chart">
      <div className="app-usage-chart__header">
        <h2 className="app-usage-chart__title">
          <GridIcon size={15} />
          Most used apps
        </h2>
        <div className="app-usage-chart__readout">
          {active ? (
            <>
              <strong>{active.app}</strong> &middot; {formatDuration(active.secs)}
            </>
          ) : (
            <span className="app-usage-chart__readout-hint">Hover a slice, click for more</span>
          )}
        </div>
      </div>
      <div className="app-usage-chart__body">
        <div className="app-usage-chart__donut-wrap">
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
                strokeWidth={hovered === i || selected === s.app ? 5 : 4}
                strokeOpacity={selected && selected !== s.app ? 0.35 : 1}
                strokeDasharray={`${s.pct} ${100 - s.pct}`}
                strokeDashoffset={s.dashoffset}
                className="app-usage-chart__slice"
                onMouseEnter={() => setHovered(i)}
                onMouseLeave={() => setHovered((h) => (h === i ? null : h))}
                onClick={() => toggleSelected(s.app)}
              >
                <title>
                  {s.app} — {formatDuration(s.secs)}
                </title>
              </circle>
            ))}
          </svg>
          <div className="app-usage-chart__donut-center">
            <strong>{formatDuration(totalSecs)}</strong>
            <span>Total time</span>
          </div>
        </div>
        <ul className="app-usage-chart__legend">
          {slices.map((s, i) => (
            <li
              key={s.app}
              className={`app-usage-chart__legend-row${hovered === i ? " app-usage-chart__legend-row--hovered" : ""}${selected === s.app ? " app-usage-chart__legend-row--selected" : ""}`}
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered((h) => (h === i ? null : h))}
              onClick={() => toggleSelected(s.app)}
              title={`${s.app} — ${formatDuration(s.secs)}`}
            >
              <span className="app-usage-chart__legend-dot" style={{ background: s.color }} />
              <span className="app-usage-chart__legend-name">{s.app}</span>
              <span className="app-usage-chart__legend-time">{formatDuration(s.secs)}</span>
            </li>
          ))}
        </ul>
      </div>

      {selected && (
        <div className="app-usage-chart__detail">
          <h3 className="app-usage-chart__detail-title">Distraction history &middot; {selected}</h3>
          {selectedMessages.length === 0 ? (
            <p className="app-usage-chart__empty">No distraction nudges recorded for this app yet.</p>
          ) : (
            <ul className="app-usage-chart__detail-list">
              {selectedMessages.map((m) => (
                <li key={m.messageId} className="app-usage-chart__detail-item">
                  <p className="app-usage-chart__detail-text">{m.text}</p>
                  <span className="app-usage-chart__detail-time">{formatRelativeTime(m.createdAt, now)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
