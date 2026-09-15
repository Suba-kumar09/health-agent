import type { ActivitySegment } from "../types";
import { formatClock } from "../format";
import "./ActivityTimeline.css";

interface ActivityTimelineProps {
  segments: ActivitySegment[];
  now: number;
}

export function ActivityTimeline({ segments, now }: ActivityTimelineProps) {
  if (segments.length === 0) return null;

  const dayStart = segments[0].startTs;
  const span = Math.max(1, now - dayStart);

  return (
    <div className="timeline">
      <div className="timeline__header">
        <h2 className="timeline__title">Today</h2>
        <div className="timeline__legend">
          <span className="timeline__legend-item">
            <span className="timeline__swatch timeline__swatch--active" /> Active
          </span>
          <span className="timeline__legend-item">
            <span className="timeline__swatch timeline__swatch--idle" /> Idle
          </span>
        </div>
      </div>

      <div className="timeline__track" role="img" aria-label="Today's active and idle periods">
        {segments.map((seg, i) => {
          const left = ((seg.startTs - dayStart) / span) * 100;
          const width = Math.max(0.4, ((seg.endTs - seg.startTs) / span) * 100);
          return (
            <div
              key={i}
              className={`timeline__segment timeline__segment--${seg.state}`}
              style={{ left: `${left}%`, width: `${width}%` }}
              title={`${seg.state === "active" ? "Active" : "Idle"}: ${formatClock(seg.startTs)}–${formatClock(seg.endTs)}`}
            />
          );
        })}
      </div>

      <div className="timeline__ticks">
        <span>{formatClock(dayStart)}</span>
        <span>{formatClock(now)}</span>
      </div>
    </div>
  );
}
