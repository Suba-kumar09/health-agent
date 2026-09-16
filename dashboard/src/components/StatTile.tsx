import type { CSSProperties, ReactNode } from "react";
import "./StatTile.css";

export type StatStatus = "good" | "warning" | "serious" | "critical";

interface StatTileProps {
  label: string;
  value: string;
  sublabel?: string;
  status?: StatStatus;
  statusLabel?: string;
  icon?: ReactNode;
  accent?: string;
}

const STATUS_TEXT: Record<StatStatus, string> = {
  good: "On track",
  warning: "Worth a look",
  serious: "Take a break",
  critical: "Overdue",
};

export function StatTile({ label, value, sublabel, status, statusLabel, icon, accent }: StatTileProps) {
  return (
    <div className="stat-tile" style={accent ? ({ "--tile-accent": accent } as CSSProperties) : undefined}>
      <div className="stat-tile__header">
        {icon && <span className="stat-tile__icon-badge">{icon}</span>}
        <span className="stat-tile__label">{label}</span>
      </div>
      <div className="stat-tile__value">{value}</div>
      {sublabel && <div className="stat-tile__sublabel">{sublabel}</div>}
      {status && (
        <div className={`stat-tile__status stat-tile__status--${status}`}>
          <span className="stat-tile__status-dot" aria-hidden="true" />
          {statusLabel ?? STATUS_TEXT[status]}
        </div>
      )}
    </div>
  );
}
