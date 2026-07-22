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
  } catch (err) {
    status.textContent = `Could not reach agent on port ${port}: ${err}`;
  }
});
