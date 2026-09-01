from __future__ import annotations

import sys
import types

from agent.tray import TrayController


def _make_controller() -> TrayController:
    return TrayController(on_pause=lambda: None, on_resume=lambda: None, on_stop=lambda: None, capture_mode="aggregate")


class _FakeIcon:
    def __init__(self):
        self.notified: list[tuple[str, str]] = []

    def notify(self, text, title):
        self.notified.append((text, title))


def test_non_windows_skips_toast_and_uses_tray_notify(monkeypatch):
    controller = _make_controller()
    controller._icon = _FakeIcon()
    monkeypatch.setattr("agent.tray.platform.system", lambda: "Darwin")

    controller.show_message("take a break")

    assert controller._icon.notified == [("take a break", "Health Agent")]


def test_no_icon_logs_instead_of_raising(monkeypatch, caplog):
    controller = _make_controller()
    monkeypatch.setattr("agent.tray.platform.system", lambda: "Darwin")

    with caplog.at_level("INFO"):
        controller.show_message("take a break")

    assert "take a break" in caplog.text


def test_windows_toast_success_skips_tray_balloon(monkeypatch):
    controller = _make_controller()
    controller._icon = _FakeIcon()
    monkeypatch.setattr("agent.tray.platform.system", lambda: "Windows")

    calls: list[list[str]] = []

    class _FakeToast:
        def __init__(self):
            self.text_fields: list[str] = []

    class _FakeWindowsToaster:
        def __init__(self, app_name):
            self.app_name = app_name

        def show_toast(self, toast):
            calls.append(toast.text_fields)

    fake_module = types.SimpleNamespace(Toast=_FakeToast, WindowsToaster=_FakeWindowsToaster)
    monkeypatch.setitem(sys.modules, "windows_toasts", fake_module)

    controller.show_message("take a break")

    assert calls == [["take a break"]]
    assert controller._icon.notified == []  # balloon fallback must not also fire


def test_windows_toast_import_error_falls_back_to_tray_balloon(monkeypatch):
    controller = _make_controller()
    controller._icon = _FakeIcon()
    monkeypatch.setattr("agent.tray.platform.system", lambda: "Windows")
    monkeypatch.setitem(sys.modules, "windows_toasts", None)  # forces ImportError on `from windows_toasts import ...`

    controller.show_message("take a break")

    assert controller._icon.notified == [("take a break", "Health Agent")]


def test_windows_toast_runtime_error_falls_back_to_tray_balloon(monkeypatch):
    controller = _make_controller()
    controller._icon = _FakeIcon()
    monkeypatch.setattr("agent.tray.platform.system", lambda: "Windows")

    class _FakeToast:
        def __init__(self):
            self.text_fields: list[str] = []

    class _BrokenWindowsToaster:
        def __init__(self, app_name):
            pass

        def show_toast(self, toast):
            raise RuntimeError("simulated WinRT failure")

    fake_module = types.SimpleNamespace(Toast=_FakeToast, WindowsToaster=_BrokenWindowsToaster)
    monkeypatch.setitem(sys.modules, "windows_toasts", fake_module)

    controller.show_message("take a break")

    assert controller._icon.notified == [("take a break", "Health Agent")]
