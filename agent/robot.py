"""Buddy's face: a small animated robot that floats on the right edge of the
screen for as long as the agent runs -- like a chat head. When a reminder
arrives, a speech bubble slides out next to it with the text, a Mute button
and a ✕; a couple of seconds after Buddy finishes speaking the bubble closes
and Buddy tucks into the screen edge (✕ closes it early).

- A small 🔊/🔇 badge on Buddy mutes/unmutes at any time. Muted Buddy stays
  quiet -- no voice, no bubble; the Windows popup still shows the reminder.
- The › button tucks Buddy into the screen edge, leaving a thin ‹ tab; click
  the tab to bring Buddy back. A reminder still pops Buddy out, then it tucks
  away again.
- Drag Buddy up or down the edge to move it; click Buddy to close the bubble.
- Hidden/shown and the dragged position are remembered (agent/buddy_settings.py).

Drawn with tkinter (Python stdlib -- no image files, no new dependency). Tk is
not thread-safe, so the window lives on its own thread and every other thread
talks to it only through a queue that the Tk thread polls. The window is
borderless, always on top, and never takes keyboard focus (on Windows it is
shown with SW_SHOWNOACTIVATE and marked WS_EX_NOACTIVATE). Its background
color is keyed out, so only the robot and bubble are visible and clicks on the
empty area pass through to the windows underneath.

The layout and animation maths are plain functions so they can be tested
without a display.
"""
from __future__ import annotations

import logging
import math
import platform
import queue
import threading
import time
from collections.abc import Callable

from agent.buddy_settings import BuddySettings

logger = logging.getLogger(__name__)

WIDTH, HEIGHT = 360, 170
EDGE_MARGIN = 6  # gap between Buddy and the right screen edge
DOCK_FRACTION = 0.64  # default height on the edge: below the middle, above the toast area
TICK_MS = 50
HIDE_AFTER_SECS = 2.5
BUBBLE_MAX_CHARS = 140
DRAG_THRESHOLD = 4  # px of movement before a press counts as a drag, not a click

IDLE_ALPHA, ACTIVE_ALPHA = 0.88, 0.98

_KEY = "#fe00fe"  # this exact color is made fully transparent (Windows)
_BLUE, _BLUE_DARK = "#2a78d6", "#1c5cab"
_SCREEN, _GLOW = "#0d2a4a", "#7fe3ff"
_INK, _BUBBLE_EDGE = "#1b2530", "#d7dde6"
_BTN_BG, _BTN_EDGE = "#e3edfb", "#b7d3f6"
_MUTED_BG = "#f3d6d6"


# ------------------------------------------------------------------ pure helpers


def dock_position(
    work_area: tuple[int, int, int, int],
    size: tuple[int, int],
    margin: int = EDGE_MARGIN,
    fraction: float = DOCK_FRACTION,
) -> tuple[int, int]:
    """Top-left (x, y) that docks a window of `size` on the right edge of
    `work_area` (left, top, right, bottom -- the screen minus the taskbar),
    with its middle at `fraction` of the work area's height."""
    left, top, right, bottom = work_area
    w, h = size
    x = max(left, right - w - margin)
    y = int(top + (bottom - top) * fraction - h / 2)
    return x, clamp_y(y, work_area, h)


def clamp_y(y: int, work_area: tuple[int, int, int, int], height: int) -> int:
    """Keeps a dragged window fully on screen vertically."""
    _, top, _, bottom = work_area
    return max(top, min(int(y), bottom - height))


def bubble_text(text: str, max_chars: int = BUBBLE_MAX_CHARS) -> str:
    """Collapses whitespace and cuts long reminders at a word boundary with "…"."""
    text = " ".join((text or "").split())
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.;:-") + "…"


def eyes_open(frame: int) -> bool:
    """Blink for three frames (~0.15 s) every 70 frames (~3.5 s)."""
    return frame % 70 not in (0, 1, 2)


def mouth_height(frame: int, speaking: bool) -> float:
    """Mouth height in px: a thin line when quiet, flapping while speaking."""
    if not speaking:
        return 3.0
    return 3.0 + 7.0 * abs(math.sin(frame * 0.9))


def mute_label(muted: bool) -> str:
    """Text on the bubble's button: what clicking it will do."""
    return "\U0001F50A Unmute" if muted else "\U0001F507 Mute"


def badge_icon(muted: bool) -> str:
    """The always-visible badge on Buddy: the current state."""
    return "\U0001F507" if muted else "\U0001F50A"


def _work_area(root) -> tuple[int, int, int, int]:
    if platform.system() == "Windows":
        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
                return rect.left, rect.top, rect.right, rect.bottom
        except Exception:  # pragma: no cover - fall back to the whole screen
            pass
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight() - 48


def _rounded_points(x1, y1, x2, y2, r) -> list[float]:
    """Polygon points that Tk's `smooth=True` turns into a rounded rectangle."""
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


def _rounded(canvas, x1, y1, x2, y2, r, **kw):
    return canvas.create_polygon(_rounded_points(x1, y1, x2, y2, r), smooth=True, **kw)


# ------------------------------------------------------------------ window


class RobotWindow:
    def __init__(
        self,
        on_toggle_mute: Callable[[], None] | None = None,
        is_muted: Callable[[], bool] | None = None,
        settings: BuddySettings | None = None,
    ) -> None:
        # The badge and the bubble's button call on_toggle_mute (Buddy's
        # voice); is_muted drives their labels and whether the mouth moves.
        self._on_toggle_mute = on_toggle_mute
        self._is_muted = is_muted or (lambda: False)
        self._settings = settings or BuddySettings()
        self._commands: queue.Queue[tuple] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self.available = False  # False if Tk couldn't start (e.g. no display)

    # ---- called from any thread

    def start(self, timeout: float = 5.0) -> None:
        """Starts the window and docks Buddy on the right edge."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="buddy-robot", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)

    def speak(self, text: str) -> None:
        """Slide out the bubble with `text` and start talking."""
        self._commands.put(("speak", text))

    def done_speaking(self, delay: float | None = HIDE_AFTER_SECS, tuck_away: bool = False) -> None:
        """Close the mouth and put the bubble away `delay` seconds later
        (`None`: leave it open until the user clicks ✕); with `tuck_away`, Buddy
        then hides into the screen edge (after the greeting)."""
        self._commands.put(("done", delay, tuck_away))

    def stop(self, timeout: float = 3.0) -> None:
        if self._thread is None:
            return
        self._commands.put(("quit",))
        self._thread.join(timeout)
        self._thread = None

    # ---- Tk thread only

    def _run(self) -> None:
        try:
            import tkinter as tk

            self._tk = tk
            self._build()
        except Exception:
            logger.warning("Buddy's robot window could not start; the voice still works", exc_info=True)
            self._ready.set()
            return
        self.available = True
        self._ready.set()
        try:
            self._root.mainloop()
        finally:
            try:
                self._root.destroy()
            except Exception:
                pass
            # Drop every Tk reference here, on the Tk thread. If the main thread
            # garbage-collects them at exit instead, Tcl aborts the process with
            # "Tcl_AsyncDelete: async handler deleted by the wrong thread".
            self._canvas = None
            self._root = None
            self._tk = None

    def _build(self) -> None:
        tk = self._tk
        root = self._root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        self._windows = platform.system() == "Windows"
        if self._windows:
            root.attributes("-transparentcolor", _KEY)
        root.configure(bg=_KEY)

        c = self._canvas = tk.Canvas(root, width=WIDTH, height=HEIGHT, bg=_KEY, highlightthickness=0, bd=0)
        c.pack()
        c.bind("<ButtonPress-1>", self._on_press)
        c.bind("<B1-Motion>", self._on_drag)
        c.bind("<ButtonRelease-1>", self._on_release)

        # Speech bubble (left of Buddy), hidden until a reminder arrives.
        bubble = ("bubble",)
        self._bubble = _rounded(c, 8, 20, 244, 128, 14, fill="white", outline=_BUBBLE_EDGE, width=1.5, tags=bubble)
        c.create_polygon(243, 66, 258, 76, 243, 86, fill="white", outline=_BUBBLE_EDGE, width=1.5, tags=bubble)
        c.create_line(243, 67, 243, 85, fill="white", width=3, tags=bubble)  # hide the edge under the tail
        c.create_text(24, 32, anchor="nw", text="Buddy", fill=_BLUE, font=("Segoe UI", 9, "bold"), tags=bubble)
        self._text = c.create_text(24, 52, anchor="nw", width=206, fill=_INK, font=("Segoe UI", 10), tags=bubble)
        btn = ("bubble", "mutebtn")
        self._btn_bg = _rounded(c, 130, 26, 204, 46, 9, fill=_BTN_BG, outline=_BTN_EDGE, width=1, tags=btn)
        self._btn_text = c.create_text(167, 36, text="", fill=_BLUE_DARK, font=("Segoe UI", 8, "bold"), tags=btn)
        # ✕ closes the bubble -- a reminder stays up until the user clicks it.
        close = ("bubble", "closebtn")
        c.create_oval(210, 26, 230, 46, fill=_BTN_BG, outline=_BTN_EDGE, width=1, tags=close)
        c.create_text(220, 36, text="✕", fill=_BLUE_DARK, font=("Segoe UI", 8, "bold"), tags=close)

        # Buddy (right). Tagged "body" so it can be dragged along the edge.
        body = ("body",)
        c.create_line(304, 24, 304, 42, fill=_BLUE_DARK, width=3, tags=body)
        self._antenna = c.create_oval(298, 14, 310, 26, fill=_GLOW, outline=_BLUE_DARK, width=2, tags=body)
        c.create_rectangle(256, 66, 264, 90, fill=_BLUE_DARK, outline="", tags=body)
        c.create_rectangle(344, 66, 352, 90, fill=_BLUE_DARK, outline="", tags=body)
        _rounded(c, 262, 42, 346, 114, 16, fill=_BLUE, outline=_BLUE_DARK, width=2, tags=body)
        _rounded(c, 272, 54, 336, 102, 10, fill=_SCREEN, outline="", tags=body)
        self._eye_l = c.create_oval(284, 65, 298, 79, fill=_GLOW, outline="", tags=body)
        self._eye_r = c.create_oval(310, 65, 324, 79, fill=_GLOW, outline="", tags=body)
        self._mouth = c.create_rectangle(294, 88, 314, 91, fill=_GLOW, outline="", tags=body)
        _rounded(c, 280, 116, 328, 150, 10, fill=_BLUE, outline=_BLUE_DARK, width=2, tags=body)
        self._chest = c.create_oval(299, 128, 309, 138, fill=_GLOW, outline="", tags=body)

        # Always-visible mute badge on Buddy's top-left corner.
        badge = ("mutebtn",)
        self._badge_bg = c.create_oval(250, 30, 276, 56, fill="white", outline=_BTN_EDGE, width=1.5, tags=badge)
        self._badge_text = c.create_text(263, 43, text="", font=("Segoe UI Emoji", 9), tags=badge)

        # "›" button on Buddy's top-right corner tucks it into the edge.
        hide = ("hidebtn",)
        c.create_oval(332, 30, 358, 56, fill="white", outline=_BTN_EDGE, width=1.5, tags=hide)
        c.create_text(345, 42, text="›", fill=_BLUE_DARK, font=("Segoe UI", 14, "bold"), tags=hide)

        # While tucked away only this thin "‹" tab on the screen edge shows.
        tab = ("tab",)
        _rounded(c, 338, 58, 362, 112, 8, fill=_BLUE, outline=_BLUE_DARK, width=1.5, tags=tab)
        c.create_text(348, 84, text="‹", fill="white", font=("Segoe UI", 16, "bold"), tags=tab)

        for tag in ("mutebtn", "closebtn", "body", "hidebtn", "tab"):
            c.tag_bind(tag, "<Enter>", lambda _e: c.configure(cursor="hand2"))
            c.tag_bind(tag, "<Leave>", lambda _e: c.configure(cursor=""))

        self._frame = 0
        self._speaking = False
        self._bubble_open = False
        self._hide_at: float | None = None
        self._press: tuple[int, int] | None = None  # (screen y at press, window y at press)
        self._dragged = False
        self._collapsed = bool(self._settings.get("hidden", False))
        self._peeking = False  # popped out for a reminder while hidden
        self._tuck_after = False  # hide into the edge once the bubble closes
        self._set_bubble(False)
        self._apply_collapsed()
        self._refresh_mute()

        root.geometry(f"{WIDTH}x{HEIGHT}")
        root.update_idletasks()
        self._dock()
        root.after(TICK_MS, self._tick)

    # ---- placement

    def _dock(self) -> None:
        self._area = _work_area(self._root)
        self._x, self._y = dock_position(self._area, (WIDTH, HEIGHT))
        saved_y = self._settings.get("y")
        if isinstance(saved_y, (int, float)):
            self._y = clamp_y(int(saved_y), self._area, HEIGHT)
        self._root.geometry(f"{WIDTH}x{HEIGHT}+{self._x}+{self._y}")
        self._root.update_idletasks()
        self._root.attributes("-alpha", IDLE_ALPHA)
        self._native_show()

    def _move_to(self, y: int) -> None:
        self._y = clamp_y(y, self._area, HEIGHT)
        if self._windows:
            try:
                import ctypes

                ctypes.windll.user32.MoveWindow(self._hwnd(), self._x, self._y, WIDTH, HEIGHT, True)
                return
            except Exception:  # pragma: no cover
                pass
        self._root.geometry(f"{WIDTH}x{HEIGHT}+{self._x}+{self._y}")

    # ---- mouse: click the badge/button to mute, drag Buddy, click Buddy to close the bubble

    def _on_press(self, event) -> None:
        self._press = (event.y_root, self._y)
        self._dragged = False

    def _on_drag(self, event) -> None:
        tags = self._canvas.gettags("current")
        if self._press is None or not ("body" in tags or "tab" in tags):
            return
        start_y, window_y = self._press
        if abs(event.y_root - start_y) >= DRAG_THRESHOLD:
            self._dragged = True
        if self._dragged:
            self._move_to(window_y + (event.y_root - start_y))

    def _on_release(self, _event) -> None:
        if self._dragged:
            self._press = None
            self._settings.set("y", self._y)  # remember where Buddy was put
            return
        self._press = None
        tags = self._canvas.gettags("current")
        if "closebtn" in tags:
            self._speaking = False
            self._begin_hide(0)
        elif "mutebtn" in tags:
            if self._on_toggle_mute is not None:
                self._on_toggle_mute()
            self._refresh_mute()
            if self._is_muted() and self._bubble_open:
                # Muted means quiet: the voice stops and the bubble closes now.
                self._speaking = False
                self._begin_hide(0)
        elif "hidebtn" in tags:
            self._set_collapsed(True)
        elif "tab" in tags:
            self._set_collapsed(False)
        elif "body" in tags and self._bubble_open:
            self._speaking = False
            self._begin_hide(0)

    # ---- commands and animation

    def _tick(self) -> None:
        try:
            while True:
                cmd = self._commands.get_nowait()
                if cmd[0] == "quit":
                    self._root.quit()
                    return
                if cmd[0] == "speak":
                    self._show(cmd[1])
                elif cmd[0] == "done":
                    self._speaking = False
                    self._tuck_after = cmd[2]
                    if cmd[1] is None:
                        self._hide_at = None  # stays until the user clicks ✕
                    else:
                        self._begin_hide(cmd[1])
        except queue.Empty:
            pass
        except Exception:
            logger.warning("Buddy's robot window hit an error", exc_info=True)
        try:
            self._animate()
        except Exception:
            logger.warning("Buddy's robot animation hit an error", exc_info=True)
        # Always reschedule: one bad frame must not freeze Buddy for good.
        self._root.after(TICK_MS, self._tick)

    def _show(self, text: str) -> None:
        c = self._canvas
        c.itemconfigure(self._text, text=bubble_text(text))
        if self._collapsed and not self._peeking:
            self._peeking = True  # pop out for this reminder, tuck back in afterwards
            self._apply_collapsed()
        # Open first: Tk reports no size (bbox None) for hidden items.
        self._set_bubble(True)
        # Grow/shrink the bubble to fit the text.
        box = c.bbox(self._text)
        text_bottom = box[3] if box else 110
        bottom = max(96, min(HEIGHT - 8, text_bottom + 14))
        c.coords(self._bubble, *_rounded_points(8, 20, 244, bottom, 14))
        self._refresh_mute()
        self._speaking = True
        self._hide_at = None
        self._root.attributes("-alpha", ACTIVE_ALPHA)

    def _set_bubble(self, open_: bool) -> None:
        self._bubble_open = open_
        self._canvas.itemconfigure("bubble", state="normal" if open_ else "hidden")

    def _set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self._peeking = False
        if collapsed:
            self._speaking = False
            self._set_bubble(False)
            self._hide_at = None
        self._settings.set("hidden", collapsed)
        self._apply_collapsed()

    def _apply_collapsed(self) -> None:
        """Tucked away: only the edge tab shows. Otherwise: Buddy and its buttons."""
        tucked = self._collapsed and not self._peeking
        c = self._canvas
        for tag in ("body", "mutebtn", "hidebtn"):
            c.itemconfigure(tag, state="hidden" if tucked else "normal")
        c.itemconfigure("tab", state="normal" if tucked else "hidden")
        if not tucked and not self._bubble_open:
            c.itemconfigure("bubble", state="hidden")  # the bubble's own button shares the mutebtn tag

    def _begin_hide(self, delay: float) -> None:
        self._hide_at = time.monotonic() + delay

    def _refresh_mute(self) -> None:
        muted = self._is_muted()
        c = self._canvas
        c.itemconfigure(self._btn_text, text=mute_label(muted))
        c.itemconfigure(self._badge_text, text=badge_icon(muted))
        c.itemconfigure(self._badge_bg, fill=_MUTED_BG if muted else "white")

    def _animate(self) -> None:
        c = self._canvas
        self._frame += 1
        f = self._frame

        if self._bubble_open and self._hide_at is not None and time.monotonic() >= self._hide_at:
            if not self._speaking:
                self._set_bubble(False)
                self._hide_at = None
                self._root.attributes("-alpha", IDLE_ALPHA)
                if self._tuck_after:
                    self._tuck_after = False
                    self._set_collapsed(True)
                elif self._peeking:
                    self._peeking = False
                    self._apply_collapsed()

        # Eyes blink; mouth flaps while speaking; antenna and chest light pulse
        # (faster while talking).
        eye_h = 7 if eyes_open(f) else 1
        c.coords(self._eye_l, 284, 72 - eye_h, 298, 72 + eye_h)
        c.coords(self._eye_r, 310, 72 - eye_h, 324, 72 + eye_h)
        mh = mouth_height(f, self._speaking and not self._is_muted())
        c.coords(self._mouth, 294, 90 - mh / 2, 314, 90 + mh / 2)
        blink_every = 4 if self._speaking else 16
        lit = (f // blink_every) % 2 == 0
        c.itemconfigure(self._antenna, fill=_GLOW if lit else _BLUE)
        c.itemconfigure(self._chest, fill=_GLOW if lit else _SCREEN)
        if f % 10 == 0:
            self._refresh_mute()  # also picks up a mute/unmute from the tray menu

    # Show without stealing keyboard focus from whatever the user is typing in.

    def _hwnd(self) -> int:
        return int(self._root.frame(), 16)

    def _native_show(self) -> None:
        if self._windows:
            try:
                import ctypes

                user32 = ctypes.windll.user32
                hwnd = self._hwnd()
                ex_style = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
                user32.SetWindowLongW(hwnd, -20, ex_style | 0x08000000 | 0x00000080)  # NOACTIVATE | TOOLWINDOW
                user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE -- stays on top via Tk's -topmost
                return
            except Exception:  # pragma: no cover - fall back to Tk
                logger.debug("native no-activate show failed", exc_info=True)
        self._root.deiconify()
