import { useRef, useState } from "react";
import { clock } from "../format";

interface Point {
  hour_start: number;
  active_secs: number;
}

const W = 640;
const H = 200;
const PAD = { l: 34, r: 8, t: 10, b: 22 };

// Single-series area chart of active minutes per hour, with a hover crosshair.
export function TrendChart({ points }: { points: Point[] }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  if (points.length < 2) return <div className="empty">No activity in the last 24 hours.</div>;

  const values = points.map((p) => p.active_secs / 60);
  const max = Math.max(...values);
  const niceMax = max <= 10 ? 10 : Math.ceil(max / 10) * 10;
  const pw = W - PAD.l - PAD.r;
  const ph = H - PAD.t - PAD.b;
  const x = (i: number) => PAD.l + (pw * i) / (points.length - 1);
  const y = (v: number) => PAD.t + ph * (1 - v / niceMax);
  const line = values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const area = `${PAD.l},${PAD.t + ph} ${line} ${PAD.l + pw},${PAD.t + ph}`;
  const ticks = [0, 6, 12, 18, points.length - 1].filter((i, n, all) => all.indexOf(i) === n);

  const onMove = (e: React.MouseEvent) => {
    const r = svgRef.current!.getBoundingClientRect();
    const lx = ((e.clientX - r.left) * W) / r.width;
    const i = Math.round(((lx - PAD.l) / pw) * (points.length - 1));
    setHover(Math.max(0, Math.min(points.length - 1, i)));
  };

  const hv = hover == null ? null : values[hover];
  return (
    <div className="linechart" style={{ position: "relative" }}>
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Active minutes per hour, last 24 hours">
        <defs>
          <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.22" />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line className="gridline" x1={PAD.l} x2={W - PAD.r} y1={y(niceMax * f)} y2={y(niceMax * f)} />
            <text className="axislabel" x={PAD.l - 6} y={y(niceMax * f) + 3} textAnchor="end">
              {Math.round(niceMax * f)}
            </text>
          </g>
        ))}
        {ticks.map((i) => (
          <text
            key={i}
            className="axislabel"
            x={x(i)}
            y={H - 6}
            textAnchor={i === 0 ? "start" : i === points.length - 1 ? "end" : "middle"}
          >
            {clock(points[i].hour_start)}
          </text>
        ))}
        <polygon points={area} fill="url(#trendFill)" />
        <polyline className="line" points={line} />
        {hover != null && hv != null && (
          <>
            <line className="crosshair" x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={PAD.t + ph} />
            <circle className="hoverdot" cx={x(hover)} cy={y(hv)} r={4.5} />
          </>
        )}
        <rect
          className="hitlayer"
          x={PAD.l}
          y={PAD.t}
          width={pw}
          height={ph}
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
        />
      </svg>
      {hover != null && hv != null && (
        <div
          className="tooltip"
          style={{
            position: "absolute",
            left: `${(x(hover) / W) * 100}%`,
            top: `${(y(hv) / H) * 100}%`,
          }}
        >
          <b>{Math.round(hv)}</b> active min
          <em>
            {clock(points[hover].hour_start)} – {clock(points[hover].hour_start + 3600)}
          </em>
        </div>
      )}
    </div>
  );
}
