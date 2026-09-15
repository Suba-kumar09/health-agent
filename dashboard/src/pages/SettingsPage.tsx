import { useEffect, useState } from "react";
import { fetchConsentSettings } from "../api";
import type { ConsentSettings } from "../types";
import { formatClock } from "../format";
import "./SettingsPage.css";

export function SettingsPage() {
  const [settings, setSettings] = useState<ConsentSettings | null>(null);

  useEffect(() => {
    fetchConsentSettings().then(setSettings);
  }, []);

  if (!settings) {
    return (
      <div className="page-loading">
        <p>Loading settings…</p>
      </div>
    );
  }

  return (
    <div className="settings-page">
      <header className="settings-page__header">
        <h1 className="settings-page__title">Settings</h1>
        <p className="settings-page__subtitle">
          What this device is tracking — read-only here; change it from the agent's tray icon.
        </p>
      </header>

      <div className="settings-card">
        <h2 className="settings-card__title">Consent</h2>
        <div className="settings-row">
          <span>Basic monitoring</span>
          <span className="settings-row__value">
            <span className="settings-row__dot settings-row__dot--good" aria-hidden="true" />
            Consented {settings.basicConsentedAt ? formatClock(settings.basicConsentedAt) : "—"}
          </span>
        </div>
        <div className="settings-row">
          <span>Detailed capture (records key content)</span>
          <span className="settings-row__value">
            <span
              className={`settings-row__dot ${settings.detailedConsentedAt ? "settings-row__dot--good" : "settings-row__dot--off"}`}
              aria-hidden="true"
            />
            {settings.detailedConsentedAt ? `Consented ${formatClock(settings.detailedConsentedAt)}` : "Not consented"}
          </span>
        </div>
        <div className="settings-row">
          <span>Capture mode</span>
          <span className="settings-row__value">
            {settings.captureMode === "aggregate" ? "Aggregate (counts only)" : "Detailed"}
          </span>
        </div>
        <div className="settings-row">
          <span>Encrypt data at rest</span>
          <span className="settings-row__value">
            <span
              className={`settings-row__dot ${settings.encryptAtRest ? "settings-row__dot--good" : "settings-row__dot--off"}`}
              aria-hidden="true"
            />
            {settings.encryptAtRest ? "On" : "Off"}
          </span>
        </div>
      </div>

      <div className="settings-card">
        <h2 className="settings-card__title">Collectors</h2>
        {settings.collectors.map((c) => (
          <div className="settings-row" key={c.name}>
            <span>{c.label}</span>
            <span className="settings-row__value">
              <span
                className={`settings-row__dot ${c.enabled ? "settings-row__dot--good" : "settings-row__dot--off"}`}
                aria-hidden="true"
              />
              {c.enabled ? "Enabled" : "Disabled"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
