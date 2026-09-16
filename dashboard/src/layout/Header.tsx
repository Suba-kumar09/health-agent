import { useEffect, useState } from "react";
import { formatHeaderDate } from "../format";
import { BellIcon } from "../components/icons";
import "./Header.css";

export function Header() {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(id);
  }, []);

  const { day, time } = formatHeaderDate(now);

  return (
    <header className="app-header">
      <div className="app-header__spacer" />
      <button className="app-header__icon-button" aria-label="Notifications" type="button">
        <BellIcon size={18} />
      </button>
      <div className="app-header__date">
        <span className="app-header__day">{day}</span>
        <span className="app-header__time">{time}</span>
      </div>
    </header>
  );
}
