from __future__ import annotations

import logging
import threading

import psutil
import win32con
import win32gui
import win32process
import win32ts

logger = logging.getLogger(__name__)

# OpenInputDesktop-based detection (checking whether the "Winlogon" secure
# desktop is active) does NOT work here: since Windows 8, the lock screen
# itself (the wallpaper/clock you see right after locking) runs as a normal
# app (LockApp.exe) on the regular interactive desktop -- the secure desktop
# only appears for the few seconds of actual password entry. Polling that
# only ever catches a near-instant blip at the start/end of a lock, not the
# real duration in between.
#
# The correct mechanism is what Windows itself uses internally: register for
# WM_WTSSESSION_CHANGE notifications (WTS_SESSION_LOCK / WTS_SESSION_UNLOCK)
# on a hidden message-only window. This needs its own message pump, so it
# runs on a dedicated daemon thread, started lazily on first call; afk.py's
# poll then just reads the flag this thread maintains.
_WM_WTSSESSION_CHANGE = 0x02B1
_WTS_SESSION_LOCK = 0x7
_WTS_SESSION_UNLOCK = 0x8
_NOTIFY_FOR_THIS_SESSION = 0

_state_lock = threading.Lock()
_is_locked = False
_listener_started = False


def _wnd_proc(hwnd, msg, wparam, lparam):
    global _is_locked
    if msg == _WM_WTSSESSION_CHANGE:
        if wparam == _WTS_SESSION_LOCK:
            with _state_lock:
                _is_locked = True
        elif wparam == _WTS_SESSION_UNLOCK:
            with _state_lock:
                _is_locked = False
        return 0
    if msg == win32con.WM_DESTROY:
        win32gui.PostQuitMessage(0)
        return 0
    return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


def _run_listener() -> None:
    try:
        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = _wnd_proc
        wc.lpszClassName = "HealthAgentSessionListener"
        class_atom = win32gui.RegisterClass(wc)
        # A real (if never-shown) top-level window, NOT a message-only
        # (HWND_MESSAGE) one -- WTS session-change notifications aren't
        # reliably delivered to message-only windows in practice, despite
        # what the docs imply. No WS_VISIBLE means it never actually appears.
        hwnd = win32gui.CreateWindow(
            class_atom, "HealthAgentSessionListener", win32con.WS_OVERLAPPED, 0, 0, 0, 0, 0, 0, wc.hInstance, None
        )
        win32ts.WTSRegisterSessionNotification(hwnd, _NOTIFY_FOR_THIS_SESSION)
        win32gui.PumpMessages()
    except Exception:
        logger.exception("Session-lock listener thread failed; lock detection will always report unlocked")


def _ensure_listener_started() -> None:
    global _listener_started
    with _state_lock:
        if _listener_started:
            return
        _listener_started = True
    threading.Thread(target=_run_listener, daemon=True, name="session-lock-listener").start()


def is_workstation_locked() -> bool:
    _ensure_listener_started()
    with _state_lock:
        return _is_locked


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
