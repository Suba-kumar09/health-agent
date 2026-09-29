import { clock, duration, STATE_LABEL, windowTitle } from "../format";
import type { Segment, Totals } from "../types";
import { STATES, TotalsTiles } from "../ui/bits";
import { useTooltip } from "../ui/Tooltip";

const HOUR = 3600;

// The visible range: the workday from 09:00 (09:00-17:00 for an 8-hour day),
// stretched to cover any earlier start or later end, snapped to whole hours.
function dayRange(segments: Segment[], dayStart: number, now: number, workday: number): [number, number] {
  const first = segments.length ? segments[0].start_ts : dayStart + 9 * HOUR;
  const last = Math.max(now, segments.length ? segments[segments.length - 1].end_ts : now);
  const start = Math.min(dayStart + 9 * HOUR, dayStart + Math.floor((first - dayStart) / HOUR) * HOUR);
  const workdayEnd = dayStart + 9 * HOUR + Math.ceil(workday / HOUR) * HOUR;
  const end = Math.max(workdayEnd, dayStart + Math.ceil((last - dayStart) / HOUR) * HOUR);
  return [start, Math.min(end, dayStart + 24 * HOUR)];
}

interface DayTimelineProps {
  segments: Segment[];
  dayStart: number;
  now: number;
  workdaySecs: number;
  compact?: boolean;
  selected?: number | null; // start_ts of the open segment
  onOpen?: (segment: Segment) => void;
}

// The day as one continuous horizontal band: each stretch of time takes its
// state's color, one after another, with no gaps or separate boxes between
// them. Time with no data (agent not running) shows as the plain track.
export function DayTimeline({ segments, dayStart, now, workdaySecs, compact, selected, onOpen }: DayTimelineProps) {
  const { tipProps } = useTooltip();
  const [start, end] = dayRange(segments, dayStart, now, workdaySecs);
  const span = end - start;
  const pct = (ts: number) => ((Math.min(Math.max(ts, start), end) - start) / span) * 100;
  const hours = span / HOUR;
  const tickEvery = hours > 10 ? 2 : 1;
  const ticks: number[] = [];
  for (let t = start; t <= end; t += tickEvery * HOUR) ticks.push(t);
  const gridlines: number[] = [];
  for (let t = start + HOUR; t < end; t += HOUR) gridlines.push(t);
  const nowInRange = now > start && now < end;

  const totals: Totals = { active: 0, distraction: 0, idle: 0, locked: 0 };
  for (const s of segments) totals[s.state] += s.end_ts - s.start_ts;

  return (
    <div className={`daytl${compact ? " compact" : ""}`}>
      {!compact && <TotalsTiles totals={totals} totalLabel="Total today" target={workdaySecs} />}
      <div className="daytl-plot">
        <div className="daytl-band">
          {gridlines.map((t) => (
            <span className="daytl-grid" key={t} style={{ left: `${pct(t)}%` }} />
          ))}
          {nowInRange && (
            <span className="daytl-future" style={{ left: `${pct(now)}%` }}>
              {!compact && end - now > 1.5 * HOUR && <em>Later today</em>}
            </span>
          )}
          {segments.map((s) => {
            const left = pct(s.start_ts);
            const width = pct(s.end_ts) - left;
            if (width <= 0) return null;
            const top = s.windows[0];
            const tip = (
              <>
                <b>{STATE_LABEL[s.state]}</b> {clock(s.start_ts)}–{clock(s.end_ts)} · {duration(s.end_ts - s.start_ts)}
                {top && (
                  <>
                    <br />
                    {top.app}: {windowTitle(top)}
                  </>
                )}
                {onOpen && <em>Click to see what was on screen</em>}
              </>
            );
            return (
              <button
                key={s.start_ts}
                className={`daytl-seg dot-${s.state}${selected === s.start_ts ? " sel" : ""}`}
                style={{ left: `${left}%`, width: `${width}%` }}
                aria-label={`${STATE_LABEL[s.state]} ${clock(s.start_ts)} to ${clock(s.end_ts)}`}
                onClick={onOpen ? () => onOpen(s) : undefined}
                tabIndex={onOpen ? 0 : -1}
                {...tipProps(tip)}
              />
            );
          })}
        </div>
        {nowInRange && (
          <div className="daytl-now" style={{ left: `${pct(now)}%` }}>
            <span>Now {clock(now)}</span>
          </div>
        )}
        <div className="daytl-axis">
          {ticks.map((t, i) => (
            <span
              key={t}
              className={i === 0 ? "first" : i === ticks.length - 1 ? "last" : undefined}
              style={{ left: `${pct(t)}%` }}
            >
              {clock(t)}
            </span>
          ))}
        </div>
      </div>
      {!compact && (
        <div className="daytl-legend">
          {STATES.map((k) => (
            <span key={k}>
              <i className={`dot-${k}`} />
              {STATE_LABEL[k]}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
