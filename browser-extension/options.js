const DEFAULT_PRIVACY_SETTINGS = {
  enabled: true,
  stripQueryStrings: true,
  skipIncognito: true,
  denylist: [],
};

async function getPairing() {
  const { bridgePort, bridgeToken } = await chrome.storage.local.get(["bridgePort", "bridgeToken"]);
  if (!bridgePort || !bridgeToken) return null;
  return { bridgePort, bridgeToken };
}

async function getPrivacySettings() {
  const { privacySettings } = await chrome.storage.local.get("privacySettings");
  return { ...DEFAULT_PRIVACY_SETTINGS, ...(privacySettings || {}) };
}

async function refreshPairingStatus() {
  const pairing = await getPairing();
  const el = document.getElementById("pairing-status");
  el.textContent = pairing ? `Paired on port ${pairing.bridgePort}.` : "Not paired.";
}

async function loadPrivacySettings() {
  const settings = await getPrivacySettings();
  document.getElementById("enabled").checked = settings.enabled;
  document.getElementById("strip-query-strings").checked = settings.stripQueryStrings;
  document.getElementById("skip-incognito").checked = settings.skipIncognito;
  document.getElementById("denylist").value = settings.denylist.join(", ");
}

document.getElementById("pair-btn").addEventListener("click", async () => {
  const port = document.getElementById("port").value.trim();
  const code = document.getElementById("code").value.trim();
  const status = document.getElementById("status");
  status.textContent = "Pairing...";

  try {
    const resp = await fetch(`http://127.0.0.1:${port}/pair`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });

    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      status.textContent = `Pairing failed: ${body.error || resp.status}`;
      return;
    }

    const { token } = await resp.json();
    await chrome.storage.local.set({ bridgePort: Number(port), bridgeToken: token });
    status.textContent = "Paired successfully.";
    await refreshPairingStatus();
  } catch (err) {
    status.textContent = `Could not reach agent on port ${port}: ${err}`;
  }
});

document.getElementById("unpair-btn").addEventListener("click", async () => {
  const status = document.getElementById("status");
  const pairing = await getPairing();

  if (pairing) {
    // Best-effort: tell the agent too, so the old token stops working immediately
    // rather than just from this browser's point of view. Unpairing locally still
    // proceeds below even if the agent isn't reachable right now.
    try {
      await fetch(`http://127.0.0.1:${pairing.bridgePort}/unpair`, {
        method: "POST",
        headers: { Authorization: `Bearer ${pairing.bridgeToken}` },
      });
    } catch (err) {
      console.debug("health-agent bridge: unpair request failed (agent offline?)", err);
    }
  }

  await chrome.storage.local.remove(["bridgePort", "bridgeToken"]);
  status.textContent = "Unpaired.";
  await refreshPairingStatus();
});

document.getElementById("save-privacy-btn").addEventListener("click", async () => {
  const denylist = document
    .getElementById("denylist")
    .value.split(",")
    .map((d) => d.trim().toLowerCase())
    .filter(Boolean);

  const settings = {
    enabled: document.getElementById("enabled").checked,
    stripQueryStrings: document.getElementById("strip-query-strings").checked,
    skipIncognito: document.getElementById("skip-incognito").checked,
    denylist,
  };

  await chrome.storage.local.set({ privacySettings: settings });
  document.getElementById("privacy-status").textContent = "Privacy settings saved.";
});

refreshPairingStatus();
loadPrivacySettings();
