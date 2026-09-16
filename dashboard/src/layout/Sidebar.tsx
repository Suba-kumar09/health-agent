import { NavLink } from "react-router-dom";
import { ChevronRightIcon, GearIcon, HistoryIcon, HomeIcon, TargetIcon, UserIcon } from "../components/icons";
import { SYSTEM_NAME } from "../config";
import "./Sidebar.css";

const NAV_ITEMS = [
  { to: "/", label: "Today", end: true, icon: <HomeIcon size={17} /> },
  { to: "/history", label: "History", icon: <HistoryIcon size={17} /> },
  { to: "/goals", label: "Goals", icon: <TargetIcon size={17} /> },
  { to: "/settings", label: "Settings", icon: <GearIcon size={17} /> },
];

export function Sidebar() {
  return (
    <nav className="sidebar">
      <div className="sidebar__brand">
        <span className="sidebar__brand-dot" aria-hidden="true" />
        Health Agent
      </div>
      <ul className="sidebar__list">
        {NAV_ITEMS.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.end}
              className={({ isActive }) => `sidebar__link${isActive ? " sidebar__link--active" : ""}`}
            >
              <span className="sidebar__link-icon">{item.icon}</span>
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
      {SYSTEM_NAME && (
        <NavLink to="/settings" className="sidebar__footer">
          <span className="sidebar__avatar">
            <UserIcon size={16} />
          </span>
          <span className="sidebar__footer-name">{SYSTEM_NAME}</span>
          <ChevronRightIcon size={14} />
        </NavLink>
      )}
    </nav>
  );
}
