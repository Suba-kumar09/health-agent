import { NavLink } from "react-router-dom";
import "./Sidebar.css";

const NAV_ITEMS = [
  { to: "/", label: "Today", end: true },
  { to: "/history", label: "History" },
  { to: "/goals", label: "Goals" },
  { to: "/settings", label: "Settings" },
];

export function Sidebar() {
  return (
    <nav className="sidebar">
      <div className="sidebar__brand">Health Agent</div>
      <ul className="sidebar__list">
        {NAV_ITEMS.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.end}
              className={({ isActive }) => `sidebar__link${isActive ? " sidebar__link--active" : ""}`}
            >
              {item.label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
