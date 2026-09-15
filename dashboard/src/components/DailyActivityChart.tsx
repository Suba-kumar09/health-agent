import { useState } from "react";
import type { DayHistoryEntry } from "../types";
import { formatDuration } from "../format";
import "./DailyActivityChart.css";

interface DailyActivityChartProps {
  entries: DayHistoryEntry[];
}

function weekdayLabel(dateStr: string): string {
  return new Date(`${dateStr}T00:00:00`).toLocaleDateString(undefined, { weekday: "short" });
}

function fullDateLabel(dateStr: string): string {
  return new Date(`${dateStr}T00:00:00`).toLocaleDateString(undefined, {
    weekday: "long",
    month: "short",
    day: "numeric",
  });
}

export function DailyActivityChart({ entries }: DailyActivityChartProps) {
  const [hovered, setHovered] = useState<number | null>(null);
  const maxSecs = Math.max(1, ...entries.map((e) => e.activeSecs));
  const active = hovered !== null ? entries[hovered] : null;

  return (
    <div className="daily-chart">
      <div className="daily-chart__header">
        <h2 className="daily-chart__title">Active time — last {entries.length} days</h2>
        <div className="daily-chart__readout">
          {active ? (
            <>
              <strong>{formatDuration(active.activeSecs)}</strong> active on {fullDateLabel(active.date)}
            </>
          ) : (
            <span className="daily-chart__readout-hint">Hover a bar for details</span>
          )}
        </div>
      </div>

      <div className="daily-chart__bars" role="img" aria-label="Active minutes per day, last two weeks">
        {entries.map((e, i) => {
          const heightPct = Math.max(2, (e.activeSecs / maxSecs) * 100);
          return (
            <div
              key={e.date}
              className="daily-chart__col"
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered((h) => (h === i ? null : h))}
            >
              <div className="daily-chart__bar-track">
                <div
                  className={`daily-chart__bar${hovered === i ? " daily-chart__bar--hovered" : ""}`}
                  style={{ height: `${heightPct}%` }}
                />
              </div>
              <span className="daily-chart__tick">{weekdayLabel(e.date)[0]}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
