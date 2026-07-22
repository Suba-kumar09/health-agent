from __future__ import annotations


def get_active_window() -> dict | None:
    """Requires Accessibility + Screen-Recording permission for the window title;

    without Screen-Recording permission, CGWindowListCopyWindowInfo still
    returns window ownership but the `kCGWindowName` (title) field comes back
    empty on modern macOS -- the app name is still available either way.
    """
    from AppKit import NSWorkspace
    import Quartz

    active_app = NSWorkspace.sharedWorkspace().frontmostApplication()
    if active_app is None:
        return None

    app_name = active_app.localizedName()
    pid = active_app.processIdentifier()

    title = None
    window_list = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
    )
    for window in window_list:
        if window.get("kCGWindowOwnerPID") == pid:
            candidate = window.get("kCGWindowName")
            if candidate:
                title = candidate
                break

    return {"app": app_name, "title": title, "pid": pid}
