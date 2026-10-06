from __future__ import annotations

import logging
import platform
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)

_WINDOWS_APP_USER_MODEL_ID = "HealthAgent.WellbeingAgent"


def _register_windows_app_identity() -> None:
    """Without an explicit AppUserModelID, Windows can silently drop a
    Shell_NotifyIcon toast/balloon from an unpackaged python.exe/pythonw.exe
    process -- no exception raised, nothing in Action Center, just nothing.
    Setting one is the standard fix; it must happen before the tray icon
    (and therefore any notify() call) is created, so this runs at the start
    of TrayController.start() rather than lazily inside show_message().
    Also called from _show_windows_toast so an agent run with --no-tray (which
    never calls start()) still gets an identity; setting it twice is harmless."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_WINDOWS_APP_USER_MODEL_ID)
    except Exception:
        logger.warning("Could not set Windows AppUserModelID; tray notifications may not appear", exc_info=True)
    _register_app_display_name()


_APP_DISPLAY_NAME = "Health Agent"
_registered_display_name = False


def _register_app_display_name() -> None:
    """Registers the AppUserModelID with Windows for the current user
    (HKCU\\Software\\Classes\\AppUserModelId\\<id>, no admin needed), so toasts and
    the notification center list them as "Health Agent" instead of the raw id.
    Once per process; never raises."""
    global _registered_display_name
    if _registered_display_name or platform.system() != "Windows":
        return
    _registered_display_name = True
    try:
        import winreg

        key_path = rf"Software\Classes\AppUserModelId\{_WINDOWS_APP_USER_MODEL_ID}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, _APP_DISPLAY_NAME)
    except Exception:
        logger.warning("Could not register the Health Agent name with Windows notifications", exc_info=True)


class TrayController:
    """Visible pause/resume/stop control, satisfying the consent-visibility

    requirement that monitoring never run as an invisible background process
    the user has no easy way to check or halt.
    """

    def __init__(
        self,
        on_pause: Callable[[], None],
        on_resume: Callable[[], None],
        on_stop: Callable[[], None],
        capture_mode: str,
        on_toggle_mute: Callable[[], None] | None = None,
        is_muted: Callable[[], bool] | None = None,
    ) -> None:
        self.on_pause = on_pause
        self.on_resume = on_resume
        self.on_stop = on_stop
        self.capture_mode = capture_mode
        # Buddy's voice (agent/voice.py); the menu item only appears when set.
        self.on_toggle_mute = on_toggle_mute
        self.is_muted = is_muted or (lambda: False)
        self.paused = False
        self._icon = None
        self._thread: threading.Thread | None = None

    def _build_icon(self):
        import pystray
        from PIL import Image, ImageDraw

        def make_image(color: str):
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse((8, 8, 56, 56), fill=color)
            return img

        self._image_running = make_image("#2e8b57" if self.capture_mode == "aggregate" else "#d2691e")
        self._image_paused = make_image("#999999")

        def toggle_pause(icon, item):
            if self.paused:
                self.paused = False
                self.on_resume()
            else:
                self.paused = True
                self.on_pause()
            icon.icon = self._image_paused if self.paused else self._image_running
            icon.update_menu()

        def stop(icon, item):
            self.on_stop()
            icon.stop()

        def toggle_mute(icon, item):
            self.on_toggle_mute()
            icon.update_menu()

        items = [pystray.MenuItem(lambda item: "Resume" if self.paused else "Pause", toggle_pause)]
        if self.on_toggle_mute is not None:
            mute_label = lambda item: "Unmute Buddy" if self.is_muted() else "Mute Buddy"  # noqa: E731
            items.append(pystray.MenuItem(mute_label, toggle_mute))
        items += [
            pystray.MenuItem(f"Capture mode: {self.capture_mode}", None, enabled=False),
            pystray.MenuItem("Stop agent", stop),
        ]
        menu = pystray.Menu(*items)
        return pystray.Icon("health-agent", self._image_running, "Health Agent", menu)

    def start(self) -> None:
        _register_windows_app_identity()
        try:
            self._icon = self._build_icon()
        except Exception as exc:  # pragma: no cover - environment-dependent (no tray/display)
            logger.warning("Tray icon unavailable, running without visible control: %s", exc)
            return
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def show_message(self, text: str) -> bool:
        """Surfaces a wellbeing message as a native OS notification.

        On Windows, tries a real WinRT Toast first (see _show_windows_toast) --
        unlike pystray's notify(), which uses the legacy Shell_NotifyIcon
        balloon-tip API, a WinRT toast is logged in Action Center and stays
        there until dismissed, instead of auto-vanishing after a few seconds
        with no way to reread it. Falls back to pystray's tray-icon notify()
        (the only option on macOS/Linux, and the fallback on Windows too if
        windows-toasts isn't installed or the call fails for any reason), and
        finally to a log line if there's no tray at all (--no-tray) or the
        backend doesn't support notify().

        Returns True if the message was surfaced (or there is genuinely no way
        to show a popup here, so retrying would be pointless), False if a
        display attempt failed -- MessagesPoller then leaves the message
        un-acked so the server re-delivers it on the next poll."""
        if platform.system() == "Windows" and self._show_windows_toast(text):
            return True
        if self._icon is None:
            logger.info("Wellbeing message (no tray): %s", text)
            return True
        try:
            self._icon.notify(text, "Health Agent")
            return True
        except NotImplementedError:  # pragma: no cover - not every backend supports notify()
            logger.info("Wellbeing message (notify unsupported): %s", text)
            return True
        except Exception:
            # notify() reaching the OS shell call doesn't guarantee a toast
            # actually appears (Focus Assist / per-app notification settings
            # can suppress it with no error at all) -- but if the shell call
            # itself throws, that's a real bug and was previously swallowed
            # silently here, making this exact failure mode undiagnosable.
            logger.exception("Failed to show wellbeing notification: %s", text)
            return False

    def record_message(self, text: str) -> bool:
        """Files `text` in the Windows notification center *without* a popup on
        screen -- used when Buddy has already shown and spoken the reminder, so
        it can still be re-read later from the taskbar's notification list.
        Returns False where that isn't possible (non-Windows, no windows-toasts);
        never raises."""
        if platform.system() != "Windows":
            return False
        return self._show_windows_toast(text, quiet=True)

    def _show_windows_toast(self, text: str, quiet: bool = False) -> bool:
        """Tries to show `text` as a real WinRT Toast notification (`quiet`:
        straight into the notification center, no popup). Returns
        True on success (caller should not also fall back to the balloon
        tip), False if windows-toasts isn't installed or the call failed for
        any other reason -- never raises, so show_message can always safely
        fall back to pystray's notify()."""
        try:
            from windows_toasts import Toast, WindowsToaster

            # Must match the AUMID set by _register_windows_app_identity() --
            # a toast filed under a different, unregistered id is silently
            # accepted (lands in Action Center, no exception) but Windows
            # refuses to pop the banner for it.
            _register_windows_app_identity()
            toaster = WindowsToaster(_WINDOWS_APP_USER_MODEL_ID)
            toast = Toast()
            toast.text_fields = [text]
            toast.attribution_text = "Health Agent"
            toast.suppress_popup = quiet
            toaster.show_toast(toast)
            return True
        except ImportError:
            logger.info("windows-toasts not installed, falling back to tray balloon notification")
            return False
        except Exception:
            logger.exception("WinRT toast failed, falling back to tray balloon notification: %s", text)
            return False
