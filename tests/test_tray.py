from __future__ import annotations

import sys
import types

import pytest

import agent.tray as tray_module
from agent.tray import TrayController

_real_register_app_display_name = tray_module._register_app_display_name


@pytest.fixture(autouse=True)
def _no_real_registry_writes(monkeypatch):
    # Several tests pretend to be on Windows; never let them write the real
    # HKCU registry. The one test for the registration uses a fake winreg.
    monkeypatch.setattr(tray_module, "_register_app_display_name", lambda: None)


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


def test_show_message_returns_true_when_surfaced(monkeypatch):
    controller = _make_controller()
    controller._icon = _FakeIcon()
    monkeypatch.setattr("agent.tray.platform.system", lambda: "Darwin")

    assert controller.show_message("take a break") is True


def test_show_message_returns_true_when_there_is_no_tray(monkeypatch):
    controller = _make_controller()
    monkeypatch.setattr("agent.tray.platform.system", lambda: "Darwin")

    assert controller.show_message("take a break") is True  # nothing more can be tried; don't retry forever


def test_show_message_returns_false_when_every_display_path_fails(monkeypatch):
    controller = _make_controller()
    monkeypatch.setattr("agent.tray.platform.system", lambda: "Windows")
    monkeypatch.setitem(sys.modules, "windows_toasts", None)  # toast unavailable

    class _BrokenIcon:
        def notify(self, text, title):
            raise RuntimeError("shell call failed")

    controller._icon = _BrokenIcon()

    assert controller.show_message("take a break") is False  # poller must leave it un-acked


def test_record_message_files_a_toast_without_a_popup(monkeypatch):
    controller = _make_controller()
    monkeypatch.setattr("agent.tray.platform.system", lambda: "Windows")
    shown: list[bool] = []

    class _FakeToast:
        def __init__(self):
            self.text_fields: list[str] = []
            self.suppress_popup = False

    class _FakeWindowsToaster:
        def __init__(self, app_name):
            pass

        def show_toast(self, toast):
            shown.append(toast.suppress_popup)

    fake_module = types.SimpleNamespace(Toast=_FakeToast, WindowsToaster=_FakeWindowsToaster)
    monkeypatch.setitem(sys.modules, "windows_toasts", fake_module)

    assert controller.record_message("take a break") is True
    assert controller.show_message("take a break") is True
    assert shown == [True, False]  # quiet copy for the notification center; normal popup otherwise


def test_record_message_is_a_no_op_off_windows(monkeypatch):
    controller = _make_controller()
    monkeypatch.setattr("agent.tray.platform.system", lambda: "Darwin")
    assert controller.record_message("take a break") is False


def test_app_name_is_registered_once_for_windows_notifications(monkeypatch):
    writes: list[tuple] = []

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    fake_winreg = types.SimpleNamespace(
        HKEY_CURRENT_USER="HKCU",
        REG_SZ=1,
        CreateKey=lambda root, path: writes.append(("key", root, path)) or _Key(),
        SetValueEx=lambda key, name, reserved, kind, value: writes.append(("value", name, value)),
    )
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
    monkeypatch.setattr("agent.tray.platform.system", lambda: "Windows")
    monkeypatch.setattr(tray_module, "_registered_display_name", False)

    _real_register_app_display_name()
    _real_register_app_display_name()  # second call is a no-op

    assert writes == [
        ("key", "HKCU", r"Software\Classes\AppUserModelId\HealthAgent.WellbeingAgent"),
        ("value", "DisplayName", "Health Agent"),
    ]
