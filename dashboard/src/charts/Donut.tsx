import { duration, STATE_LABEL } from "../format";
import type { SegmentState, Totals } from "../types";
import { LegendDot, STATES } from "../ui/bits";

const COLOR: Record<SegmentState, string> = {
  active: "var(--good)",
  distraction: "var(--critical)",
  idle: "var(--warning)",
  locked: "var(--locked)",
};

// Part-to-whole of tracked time. Each legend row opens that category's details.
export function Donut({ totals, onOpen }: { totals: Totals; onOpen: (state: SegmentState) => void }) {
  const all = STATES.reduce((s, k) => s + totals[k], 0);
  let acc = 0;
  const stops: string[] = [];
  if (all > 0) {
    for (const k of STATES) {
      if (totals[k] <= 0) continue;
      const a = (acc / all) * 360;
      const b = ((acc + totals[k]) / all) * 360;
      // A thin surface-colored gap separates neighboring slices.
      const gapStart = Math.max(a, b - 0.8);
      stops.push(`${COLOR[k]} ${a.toFixed(2)}deg ${gapStart.toFixed(2)}deg`);
      stops.push(`var(--surface) ${gapStart.toFixed(2)}deg ${b.toFixed(2)}deg`);
      acc += totals[k];
    }
  }
  return (
    <div className="donut-wrap">
      <div
        className="donut"
        role="img"
        aria-label="Share of tracked time by category"
        style={stops.length ? { background: `conic-gradient(${stops.join(",")})` } : undefined}
      >
        <div className="donut-center">
          <strong>{duration(all)}</strong>
          <span>tracked today</span>
        </div>
      </div>
      <div className="legend">
        {STATES.map((k) => (
          <button className="legend-row" key={k} onClick={() => onOpen(k)}>
            <LegendDot state={k} />
            <span className="lbl">{STATE_LABEL[k]}</span>
            <span className="val">{duration(totals[k])}</span>
            <span className="pct">{all > 0 ? Math.round((totals[k] / all) * 100) : 0}%</span>
          </button>
        ))}
      </div>
    </div>
  );
}
