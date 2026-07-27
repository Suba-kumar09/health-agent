from __future__ import annotations

import logging
import threading
from collections.abc import Callable

logger = logging.getLogger(__name__)


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
        on_pair: Callable[[], tuple[int | None, str]] | None = None,
        on_unpair: Callable[[], None] | None = None,
    ) -> None:
        self.on_pause = on_pause
        self.on_resume = on_resume
        self.on_stop = on_stop
        self.capture_mode = capture_mode
        # None when browser_bridge is disabled in config -- no pairing menu items then.
        self.on_pair = on_pair
        self.on_unpair = on_unpair
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

        def pair(icon, item):
            port, code = self.on_pair()
            message = f"Port {port}, code {code} (valid 5 min) -- enter these in the extension's options page."
            try:
                icon.notify(message, "Pair browser extension")
            except NotImplementedError:  # pragma: no cover - not every backend supports notify()
                pass  # already logged at INFO by issue_pairing_code()

        def unpair(icon, item):
            self.on_unpair()
            try:
                icon.notify("Browser extension unpaired.", "Health Agent")
            except NotImplementedError:  # pragma: no cover - not every backend supports notify()
                pass

        menu_items = [
            pystray.MenuItem(lambda item: "Resume" if self.paused else "Pause", toggle_pause),
            pystray.MenuItem(f"Capture mode: {self.capture_mode}", None, enabled=False),
        ]
        if self.on_pair is not None:
            menu_items.append(pystray.MenuItem("Pair browser extension...", pair))
        if self.on_unpair is not None:
            menu_items.append(pystray.MenuItem("Unpair", unpair))
        menu_items.append(pystray.MenuItem("Stop agent", stop))

        menu = pystray.Menu(*menu_items)
        return pystray.Icon("health-agent", self._image_running, "Health Agent", menu)

    def start(self) -> None:
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
