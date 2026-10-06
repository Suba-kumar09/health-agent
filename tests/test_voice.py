from __future__ import annotations

import threading
import time

from agent.buddy_settings import BuddySettings
from agent.config import VoiceSection
from agent.voice import AFTER_SPEECH_SECS, NullSpeaker, VoiceAssistant, create_buddy, silent_secs, to_sapi_xml


class _FakeSpeaker:
    def __init__(self, fail_on: str | None = None, gate: threading.Event | None = None, long: bool = False):
        self.spoken: list[str] = []
        self.stopped: list[str] = []
        self.opened = self.closed = False
        self.fail_on = fail_on
        self.gate = gate
        self.long = long  # simulate a long sentence that can be cut off

    def open(self):
        self.opened = True

    def speak(self, text, should_stop=None):
        if self.gate is not None:
            self.gate.wait(2)
        if text == self.fail_on:
            raise RuntimeError("speaker broke")
        if self.long:
            for _ in range(100):  # up to ~2s of "speech"
                if should_stop is not None and should_stop():
                    self.stopped.append(text)
                    return
                time.sleep(0.02)
        self.spoken.append(text)

    def close(self):
        self.closed = True


def _assistant(speaker, **kw) -> VoiceAssistant:
    va = VoiceAssistant(lambda: speaker, **kw)
    va.start()
    return va


def test_speaks_messages_in_order_one_at_a_time():
    speaker = _FakeSpeaker()
    events: list[str] = []
    va = _assistant(
        speaker, on_start=lambda t: events.append(f"start:{t}"), on_end=lambda d, tuck: events.append("end")
    )

    assert va.say("first") and va.say("second")
    assert va.wait_until_idle()
    va.stop()

    assert speaker.spoken == ["first", "second"]
    assert events == ["start:first", "end", "start:second", "end"]
    assert speaker.opened and speaker.closed


def test_say_never_blocks_while_speaking():
    gate = threading.Event()
    va = _assistant(_FakeSpeaker(gate=gate))
    try:
        assert va.say("slow one")
        assert va.say("queued behind it")  # returns immediately even though speech is stuck
    finally:
        gate.set()
        va.wait_until_idle()
        va.stop()


def test_muted_buddy_stays_completely_quiet():
    speaker = _FakeSpeaker()
    shown = []
    va = _assistant(speaker, on_start=shown.append)
    va.set_muted(True)

    assert va.say("only the Windows popup shows this") is False
    va.wait_until_idle()
    va.stop()

    assert shown == []  # no bubble
    assert speaker.spoken == []  # no voice


def test_muted_after_queueing_is_skipped_too():
    gate = threading.Event()
    started = threading.Event()
    speaker = _FakeSpeaker(gate=gate)
    shown = []

    def on_start(text):
        shown.append(text)
        started.set()

    va = _assistant(speaker, on_start=on_start)
    va.say("first")  # starts, then blocks on the gate
    va.say("queued second")
    assert started.wait(2)
    va.set_muted(True)
    gate.set()
    va.wait_until_idle()
    va.stop()
    assert shown == ["first"]


def test_muting_mid_sentence_stops_the_voice_at_once():
    speaker = _FakeSpeaker(long=True)
    ends = []
    va = _assistant(speaker, on_end=lambda d, tuck: ends.append(d))

    va.say("a long reminder that gets cut off")
    time.sleep(0.1)
    va.set_muted(True)
    va.wait_until_idle()
    va.stop()

    assert speaker.stopped == ["a long reminder that gets cut off"]
    assert speaker.spoken == []
    assert ends == [0.0]  # bubble closes at once


def test_paused_agent_shows_and_says_nothing():
    speaker = _FakeSpeaker()
    shown = []
    va = _assistant(speaker, on_start=shown.append)
    va.paused = True
    assert va.say("hidden") is False
    va.stop()
    assert shown == [] and speaker.spoken == []


def test_toggle_mute():
    va = VoiceAssistant(NullSpeaker)
    va.toggle_mute()
    assert va.muted is True
    va.toggle_mute()
    assert va.muted is False


def test_mute_choice_is_remembered_across_restarts(tmp_path):
    state = tmp_path / "buddy.json"
    first = VoiceAssistant(NullSpeaker, settings=BuddySettings(state))
    assert first.muted is False
    first.set_muted(True)

    second = VoiceAssistant(NullSpeaker, settings=BuddySettings(state))
    assert second.muted is True


def test_a_broken_state_file_starts_unmuted(tmp_path):
    state = tmp_path / "buddy.json"
    state.write_text("not json")
    assert VoiceAssistant(NullSpeaker, settings=BuddySettings(state)).muted is False


def test_blank_text_is_ignored():
    va = _assistant(_FakeSpeaker())
    assert va.say("   ") is False
    va.stop()


def test_a_speaker_error_is_logged_not_raised_and_robot_still_closes(caplog):
    speaker = _FakeSpeaker(fail_on="boom")
    ends = []
    va = _assistant(speaker, on_end=lambda d, tuck: ends.append(d))

    va.say("boom")
    va.say("after")
    va.wait_until_idle()
    va.stop()

    assert speaker.spoken == ["after"]
    assert len(ends) == 2  # on_end ran even for the failed one
    assert "could not speak" in caplog.text


def test_a_voice_that_cannot_open_falls_back_to_logging(caplog):
    def broken_factory():
        raise OSError("no SAPI here")

    va = VoiceAssistant(broken_factory)
    va.start()
    va.say("still fine")
    assert va.wait_until_idle()
    va.stop()
    assert "could not start" in caplog.text


def test_queue_is_capped_so_stale_reminders_are_skipped():
    gate = threading.Event()
    va = _assistant(_FakeSpeaker(gate=gate))
    try:
        results = [va.say(f"m{i}") for i in range(20)]
        assert results.count(False) > 0  # overflow dropped, never blocked
    finally:
        gate.set()
        va.wait_until_idle()
        va.stop()


def test_sapi_xml_escapes_titles():
    xml = to_sapi_xml('Watching "Tom & Jerry <HD>"', pitch=6)
    assert xml == '<pitch absmiddle="6">Watching "Tom &amp; Jerry &lt;HD&gt;"</pitch>'


def test_create_buddy_respects_disabled_config():
    assert create_buddy(VoiceSection(enabled=False)) is None


def test_null_speaker_logs(caplog):
    with caplog.at_level("INFO"):
        NullSpeaker().speak("hello")
    assert "hello" in caplog.text


def test_greeting_when_muted_is_shown_without_voice_then_buddy_tucks_away():
    speaker = _FakeSpeaker()
    shown, ends = [], []
    va = _assistant(speaker, on_start=shown.append, on_end=lambda d, tuck: ends.append((d, tuck)))
    va.set_muted(True)

    assert va.say("Hi, I'm Buddy.", force=True, tuck_away=True)
    assert va.say("a normal reminder") is False  # muted: the Windows popup shows it instead
    va.wait_until_idle()
    va.stop()

    assert shown == ["Hi, I'm Buddy."]  # the bubble shows it...
    assert speaker.spoken == []  # ...without the voice
    assert ends == [(silent_secs("Hi, I'm Buddy."), True)]  # up long enough to read, then Buddy hides


def test_greeting_when_unmuted_is_spoken_then_buddy_hides():
    speaker = _FakeSpeaker()
    ends = []
    va = _assistant(speaker, on_end=lambda d, tuck: ends.append((d, tuck)))

    va.say("Hi, I'm Buddy.", force=True, tuck_away=True)
    va.wait_until_idle()
    va.stop()

    assert speaker.spoken == ["Hi, I'm Buddy."]
    assert ends == [(AFTER_SPEECH_SECS, True)]  # closes by itself, then Buddy hides


def test_muting_during_the_greeting_still_cuts_it_off():
    speaker = _FakeSpeaker(long=True)
    va = _assistant(speaker)
    va.say("Hi, I'm Buddy.", force=True, tuck_away=True)
    time.sleep(0.1)
    va.set_muted(True)  # was unmuted when it started
    va.wait_until_idle()
    va.stop()
    assert speaker.stopped == ["Hi, I'm Buddy."]


class _Robot:
    available = True


def test_will_present_only_when_unmuted_unpaused_and_robot_is_up():
    va = VoiceAssistant(NullSpeaker)
    assert va.will_present() is False  # no robot window
    va.robot = _Robot()
    assert va.will_present() is True
    va.muted = True
    assert va.will_present() is False  # muted -> the Windows popup shows it instead
    va.muted = False
    va.paused = True
    assert va.will_present() is False
    va.paused = False
    va.robot.available = False
    assert va.will_present() is False  # window failed to start -> popup


def test_a_reminder_closes_by_itself_after_buddy_finishes_speaking():
    speaker = _FakeSpeaker()
    ends = []
    va = _assistant(speaker, on_end=lambda d, tuck: ends.append((d, tuck)))
    va.say("Stand up and stretch!", tuck_away=True)
    va.wait_until_idle()
    va.stop()
    assert ends == [(AFTER_SPEECH_SECS, True)]


def test_silent_bubble_time_is_bounded():
    assert silent_secs("short") == 4.0
    assert silent_secs("word " * 200) == 9.0
