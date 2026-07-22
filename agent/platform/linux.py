from __future__ import annotations

import os


def is_wayland() -> bool:
    return os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))


def get_active_window() -> dict | None:
    """X11 only -- Wayland has no equivalent cross-desktop active-window API.

    Callers should check is_wayland() first and disable/warn instead of
    calling this (this is the known Phase-1 limitation the plan calls out).
    """
    if is_wayland():
        raise RuntimeError("Wayland session detected -- X11 window watcher is unavailable")

    from Xlib import display
    import psutil

    d = display.Display()
    root = d.screen().root
    net_active_window = d.intern_atom("_NET_ACTIVE_WINDOW")
    net_wm_name = d.intern_atom("_NET_WM_NAME")
    net_wm_pid = d.intern_atom("_NET_WM_PID")

    active = root.get_full_property(net_active_window, 0)
    if not active or not active.value[0]:
        return None
    window_id = active.value[0]
    window = d.create_resource_object("window", window_id)

    title_prop = window.get_full_property(net_wm_name, 0)
    title = title_prop.value.decode("utf-8") if title_prop and isinstance(title_prop.value, bytes) else title_prop.value if title_prop else None

    pid_prop = window.get_full_property(net_wm_pid, 0)
    pid = pid_prop.value[0] if pid_prop else None

    app = None
    if pid:
        try:
            app = psutil.Process(pid).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            app = None

    return {"app": app, "title": title, "pid": pid}
