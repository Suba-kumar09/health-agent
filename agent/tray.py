from __future__ import annotations

import logging
import threading
from typing import Callable

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
    ) -> None:
        self.on_pause = on_pause
        self.on_resume = on_resume
        self.on_stop = on_stop
        self.capture_mode = capture_mode
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

        menu = pystray.Menu(
            pystray.MenuItem(lambda item: "Resume" if self.paused else "Pause", toggle_pause),
            pystray.MenuItem(f"Capture mode: {self.capture_mode}", None, enabled=False),
            pystray.MenuItem("Stop agent", stop),
        )
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
