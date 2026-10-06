"""Buddy, the robot voice assistant: speaks wellbeing reminders aloud.

Reminders come from the server (via agent/sync/messages.py), so Buddy is only
ever heard while both the agent and the server are running. Speech runs on
one background worker thread, one message at a time: `say()` returns at once,
so neither the popup nor the server ack ever waits for the voice, and a voice
failure can never break notifications -- it is logged, never raised.

Muting (the badge on the robot, or the tray menu) is remembered across agent
restarts. While muted Buddy stays completely quiet -- no voice and no bubble;
the reminder is still shown by the normal Windows popup. Muting mid-sentence
stops the voice and closes the bubble at once.

On Windows the voice is the built-in SAPI text-to-speech engine (offline, free,
through pywin32), pitched up a little so it sounds like a small robot. Other
platforms fall back to `NullSpeaker`, which only logs.
"""
from __future__ import annotations

import logging
import platform
import queue
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from xml.sax.saxutils import escape

from agent.buddy_settings import BuddySettings
from agent.config import VoiceSection

logger = logging.getLogger(__name__)

GREETING = "Hi, I'm Buddy. I'll remind you to take breaks and stay focused today."

# SAPI SpeakFlags.
_SVSF_ASYNC = 1  # return at once; poll WaitUntilDone so speech can be stopped
_SVSF_PURGE = 2  # drop whatever is being spoken
_SVSF_IS_XML = 8  # treat the text as SAPI XML (so <pitch> works)
# Reminders arrive minutes apart; a backlog this long means something is stuck,
# and reading out a pile of stale reminders is worse than skipping them.
_MAX_QUEUED = 5

StopCheck = Callable[[], bool]


AFTER_SPEECH_SECS = 2.0  # bubble lingers this long after Buddy finishes speaking


def silent_secs(text: str) -> float:
    """How long a bubble shown without the voice stays up: time to read it."""
    return min(9.0, max(4.0, len(text.split()) / 3.0))


class Speaker(Protocol):
    def open(self) -> None: ...
    def speak(self, text: str, should_stop: StopCheck | None = None) -> None: ...
    def close(self) -> None: ...


class NullSpeaker:
    """No text-to-speech available: log what would have been said."""

    def open(self) -> None:
        pass

    def speak(self, text: str, should_stop: StopCheck | None = None) -> None:
        logger.info("Buddy (no voice available): %s", text)

    def close(self) -> None:
        pass


def to_sapi_xml(text: str, pitch: int) -> str:
    """Wraps `text` for SAPI's XML mode. The text is escaped, so a reminder that
    happens to contain "<" or "&" (e.g. a video title) is read, not parsed."""
    return f'<pitch absmiddle="{int(pitch)}">{escape(text)}</pitch>'


class SapiSpeaker:
    """Windows built-in text-to-speech (SAPI 5) via COM.

    COM objects belong to the thread that created them, so `open()`, `speak()`
    and `close()` must all be called from the same (worker) thread."""

    def __init__(self, rate: int, pitch: int, volume: int, voice_name: str = "") -> None:
        self.rate = rate
        self.pitch = pitch
        self.volume = volume
        self.voice_name = voice_name.strip().lower()
        self._voice = None

    def open(self) -> None:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        voice.Rate = self.rate
        voice.Volume = self.volume
        if self.voice_name:
            voices = voice.GetVoices()
            for i in range(voices.Count):
                if self.voice_name in voices.Item(i).GetDescription().lower():
                    voice.Voice = voices.Item(i)
                    break
            else:
                logger.warning("Windows voice %r not installed; using the default voice", self.voice_name)
        self._voice = voice

    def speak(self, text: str, should_stop: StopCheck | None = None) -> None:
        if self._voice is None:
            raise RuntimeError("SapiSpeaker.open() was not called")
        self._voice.Speak(to_sapi_xml(text, self.pitch), _SVSF_IS_XML | _SVSF_ASYNC)
        # Wait in short steps so a "Mute" click can cut the sentence off.
        while not self._voice.WaitUntilDone(100):
            if should_stop is not None and should_stop():
                self._voice.Speak("", _SVSF_PURGE)
                return

    def close(self) -> None:
        self._voice = None
        try:
            import pythoncom

            pythoncom.CoUninitialize()
        except Exception:  # pragma: no cover - best effort at shutdown
            pass


class VoiceAssistant:
    """Queues text and speaks it on a worker thread. `on_start(text)` and
    `on_end(delay, tuck_away)` fire around each message -- the robot window
    uses them to appear, move its mouth, close the bubble `delay` seconds later
    and, with `tuck_away`, hide itself into the screen edge."""

    def __init__(
        self,
        speaker_factory: Callable[[], Speaker],
        on_start: Callable[[str], None] | None = None,
        on_end: Callable[[float | None, bool], None] | None = None,
        settings: BuddySettings | None = None,
    ) -> None:
        self._speaker_factory = speaker_factory
        self.on_start = on_start
        self.on_end = on_end
        self.settings = settings or BuddySettings()
        # Items are (text, force, tuck_away); None stops the worker.
        self._queue: queue.Queue[tuple[str, bool, bool] | None] = queue.Queue(maxsize=_MAX_QUEUED)
        self._thread: threading.Thread | None = None
        # User's choice (robot badge / tray), remembered across restarts.
        self.muted = bool(self.settings.get("muted", False))
        self.paused = False  # agent paused from the tray: Buddy shows nothing at all
        self.robot = None  # RobotWindow, when one is shown alongside the voice

    # ---- mute state

    def set_muted(self, muted: bool) -> None:
        self.muted = muted
        logger.info("Buddy voice %s", "muted" if muted else "unmuted")
        self.settings.set("muted", muted)

    def toggle_mute(self) -> None:
        self.set_muted(not self.muted)

    # ---- queueing

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="buddy-voice", daemon=True)
            self._thread.start()

    def will_present(self) -> bool:
        """True when a reminder handed to Buddy will actually be seen and heard:
        unmuted, not paused, and the robot window is up. The agent uses this to
        decide between Buddy and the plain Windows popup -- never both."""
        robot = self.robot
        return not self.muted and not self.paused and robot is not None and robot.available

    def say(self, text: str, force: bool = False, tuck_away: bool = False) -> bool:
        """Queues `text` to be spoken with Buddy's bubble. `force` shows it even
        while muted -- in the bubble, without the voice (the start-up greeting);
        `tuck_away` tucks Buddy into the screen edge once it is done. Returns False (and drops it) when paused,
        muted (unless forced), blank, or the queue is full. Never blocks/raises."""
        text = (text or "").strip()
        if not text or self.paused or (self.muted and not force):
            return False
        try:
            self._queue.put_nowait((text, force, tuck_away))
            return True
        except queue.Full:
            logger.warning("Buddy is behind (%d messages queued); skipping: %s", _MAX_QUEUED, text)
            return False

    def wait_until_idle(self, timeout: float = 5.0) -> bool:
        """Test helper: True once everything queued so far has been handled."""
        done = threading.Event()

        def _wait() -> None:
            self._queue.join()
            done.set()

        threading.Thread(target=_wait, daemon=True).start()
        return done.wait(timeout)

    def stop(self, timeout: float = 3.0) -> None:
        if self._thread is None:
            return
        try:
            self._queue.put(None, timeout=timeout)
        except queue.Full:  # pragma: no cover - worker stuck mid-speech
            pass
        self._thread.join(timeout=timeout)
        self._thread = None

    # ---- worker thread

    def _run(self) -> None:
        try:
            speaker = self._speaker_factory()
            speaker.open()
        except Exception:
            logger.warning("Buddy's voice could not start; reminders will be shown but not spoken", exc_info=True)
            speaker = NullSpeaker()
        try:
            while True:
                item = self._queue.get()
                try:
                    if item is None:
                        return
                    text, force, tuck_away = item
                    if not self.paused and (force or not self.muted):  # muted after it was queued
                        self._handle(speaker, text, force, tuck_away)
                finally:
                    self._queue.task_done()
        finally:
            speaker.close()

    def _handle(self, speaker: Speaker, text: str, force: bool, tuck_away: bool) -> None:
        if self.muted:
            # Only a forced message (the greeting) gets here while muted: show it
            # in the bubble without the voice, long enough to read, then hide.
            self._safe(self.on_start, text)
            self._safe(self.on_end, silent_secs(text), tuck_away)
            return

        def cut_off() -> bool:
            # Stop when paused, or when the user mutes during this message.
            return self.paused or self.muted

        self._safe(self.on_start, text)
        try:
            speaker.speak(text, should_stop=cut_off)
        except Exception:
            logger.warning("Buddy could not speak a reminder", exc_info=True)
        # Done speaking: the bubble closes by itself shortly after (at once if
        # muted/paused mid-sentence) and Buddy hides into the screen edge. The ✕
        # on the bubble still closes it early.
        self._safe(self.on_end, 0.0 if cut_off() else AFTER_SPEECH_SECS, tuck_away)

    @staticmethod
    def _safe(callback: Callable[..., None] | None, *args) -> None:
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:
            logger.warning("Buddy robot callback failed", exc_info=True)


def create_buddy(cfg: VoiceSection, state_dir: str | Path | None = None) -> VoiceAssistant | None:
    """Builds and starts Buddy from config, or returns None when Buddy is turned
    off. The robot window is optional and independent: if it can't start (no
    display), Buddy still speaks. The mute choice is saved in `state_dir`."""
    if not cfg.enabled:
        logger.info("Buddy voice disabled in config")
        return None

    def speaker_factory() -> Speaker:
        if platform.system() == "Windows":
            return SapiSpeaker(rate=cfg.rate, pitch=cfg.pitch, volume=cfg.volume, voice_name=cfg.voice_name)
        return NullSpeaker()

    settings = BuddySettings(Path(state_dir) / "buddy.json" if state_dir is not None else None)
    assistant = VoiceAssistant(speaker_factory, settings=settings)

    if cfg.robot:
        from agent.robot import RobotWindow

        robot = RobotWindow(on_toggle_mute=assistant.toggle_mute, is_muted=lambda: assistant.muted, settings=settings)
        robot.start()
        assistant.robot = robot
        assistant.on_start = robot.speak
        assistant.on_end = robot.done_speaking

    assistant.start()
    logger.info("Buddy started (robot=%s, muted=%s)", assistant.robot is not None, assistant.muted)
    return assistant


def stop_buddy(assistant: VoiceAssistant | None) -> None:
    if assistant is None:
        return
    assistant.stop()
    if assistant.robot is not None:
        assistant.robot.stop()
