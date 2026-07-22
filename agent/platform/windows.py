from __future__ import annotations

import psutil
import win32gui
import win32process


def get_active_window() -> dict | None:
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None

    title = win32gui.GetWindowText(hwnd)
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        app = psutil.Process(pid).name()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pid = None
        app = None

    return {"app": app, "title": title, "pid": pid}
