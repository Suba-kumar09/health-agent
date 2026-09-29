from __future__ import annotations

import uuid

from server.activity import (
    DeviceEvents,
    app_display_name,
    build_segments,
    clean_title,
    distraction_keyword,
    hourly_active,
    site_of,
    state_totals,
    window_totals,
)
from server.models import Event

KEYWORDS = ["youtube", "instagram"]
EXEMPT = ["lecture", "tutorial"]


def _ev(collector: str, ts: float, duration: float = 0.0, **data) -> Event:
    return Event(event_id=str(uuid.uuid4()), device_id="d", collector=collector, ts=ts, duration=duration, data=data,
                 batch_id="b")


def _afk_run(start: float, end: float, state: str, step: float = 15.0) -> list[Event]:
    """Mimics the real agent: one short afk row every `step` seconds."""
    rows, t = [], start
    while t < end:
        rows.append(_ev("afk", t, min(step, end - t) - 5, state=state))
        t += step
    return rows


def _build(afk, windows=(), tabs=(), start=0.0, end=10_000.0):
    return build_segments(DeviceEvents(list(afk), list(windows), list(tabs)), start, end, KEYWORDS, EXEMPT)


def test_title_and_app_cleanup():
    assert clean_title("(596) Funny cats - YouTube - Google Chrome") == "Funny cats - YouTube"
    assert clean_title(".env - claude agent - Visual Studio Code") == ".env - claude agent"
    assert clean_title("Budget FY27.xlsx - Excel") == "Budget FY27.xlsx"
    assert clean_title("Notes on Excel") == "Notes on Excel"  # only a trailing " - App" is removed
    assert clean_title("✳ Health agent analysis") == clean_title("◐ Health agent analysis")
    assert clean_title("● main.py - project - Visual Studio Code") == "main.py - project"
    assert clean_title(".env - claude agent") == ".env - claude agent"
    assert app_display_name("chrome.exe") == "Chrome"
    assert app_display_name("Code.exe") == "VS Code"
    assert app_display_name("someTool.exe") == "SomeTool"
    assert site_of("https://www.youtube.com/watch?v=1") == "youtube.com"


def test_exempt_keyword_wins_over_distraction_keyword():
    assert distraction_keyword({"title": "Cats - YouTube"}, KEYWORDS, EXEMPT) == "youtube"
    assert distraction_keyword({"title": "Linear algebra lecture - YouTube"}, KEYWORDS, EXEMPT) is None


def test_short_afk_rows_merge_into_one_active_segment_with_its_windows():
    afk = _afk_run(0, 600, "active")
    windows = [
        _ev("window_watcher", 0, 300, app="Code.exe", title="orchestrator.py - health-agent"),
        _ev("window_watcher", 300, 300, app="slack.exe", title="#design-team"),
    ]

    segments = _build(afk, windows, end=600)

    assert [s.state for s in segments] == ["active"]
    assert round(segments[0].secs) == 600
    titles = {w.title: round(w.secs) for w in segments[0].top_windows()}
    assert titles == {"orchestrator.py - health-agent": 300, "#design-team": 300}


def test_distraction_splits_active_time_and_keeps_the_tab_title():
    afk = _afk_run(0, 900, "active")
    windows = [
        _ev("window_watcher", 0, 300, app="Code.exe", title="main.py"),
        _ev("window_watcher", 300, 300, app="chrome.exe", title="Top 10 IPL finishes - YouTube - Google Chrome"),
        _ev("window_watcher", 600, 300, app="Code.exe", title="main.py"),
    ]

    segments = _build(afk, windows, end=900)

    assert [s.state for s in segments] == ["active", "distraction", "active"]
    distraction = segments[1]
    assert round(distraction.start) == 300 and round(distraction.end) == 600
    (w,) = distraction.top_windows()
    assert (w.app, w.title, w.flag) == ("Chrome", "Top 10 IPL finishes - YouTube", "youtube")


def test_a_brief_glance_at_a_flagged_tab_stays_active():
    afk = _afk_run(0, 600, "active")
    windows = [
        _ev("window_watcher", 0, 290, app="Code.exe", title="main.py"),
        _ev("window_watcher", 290, 10, app="chrome.exe", title="Cats - YouTube - Google Chrome"),
        _ev("window_watcher", 300, 300, app="Code.exe", title="main.py"),
    ]

    segments = _build(afk, windows, end=600)

    assert [s.state for s in segments] == ["active"]
    flagged = [w for w in window_totals(segments) if w.flag]
    assert flagged and flagged[0].title == "Cats - YouTube"  # still listed, just not its own segment


def test_idle_and_locked_segments():
    afk = _afk_run(0, 300, "active") + _afk_run(300, 600, "afk") + _afk_run(600, 900, "locked")
    windows = [_ev("window_watcher", 0, 900, app="outlook.exe", title="Inbox")]

    segments = _build(afk, windows, end=900)

    assert [s.state for s in segments] == ["active", "idle", "locked"]
    assert segments[1].top_windows()[0].title == "Inbox"  # what was on screen while idle
    assert segments[2].windows == {}
    totals = state_totals(segments)
    assert round(totals["active"]) == 300 and round(totals["idle"]) == 300 and round(totals["locked"]) == 300
    # Idle time isn't counted as "using" a window.
    assert round(window_totals(segments)[0].secs) == 300


def test_a_short_pause_between_work_counts_as_working():
    afk = _afk_run(0, 300, "active") + _afk_run(300, 360, "afk") + _afk_run(360, 600, "active")

    segments = _build(afk, end=600)

    assert [s.state for s in segments] == ["active"]


def test_a_long_pause_stays_idle():
    afk = _afk_run(0, 300, "active") + _afk_run(300, 600, "afk") + _afk_run(600, 900, "active")

    segments = _build(afk, end=900)

    assert [s.state for s in segments] == ["active", "idle", "active"]


def test_gap_while_agent_was_off_is_not_filled_in():
    afk = _afk_run(0, 300, "active") + _afk_run(3600, 3900, "active")

    segments = _build(afk, end=10_000)

    assert len(segments) == 2
    # Each run ends at its last row's own duration (285+10), never stretched
    # across the hour the agent was off.
    assert [round(s.end) for s in segments] == [295, 3895]


def test_segments_are_clipped_to_the_requested_window():
    afk = _afk_run(0, 1200, "active")

    segments = _build(afk, start=600, end=900)

    assert round(segments[0].start) == 600 and round(segments[-1].end) == 900


def test_browser_tab_url_supplies_the_site():
    afk = _afk_run(0, 300, "active")
    windows = [_ev("window_watcher", 0, 300, app="chrome.exe", title="Survey results - Google Sheets - Google Chrome")]
    sheet_url = "https://docs.google.com/spreadsheets/d/1"
    tabs = [_ev("browser_bridge", 0, 300, url=sheet_url, title="Survey results - Google Sheets")]

    (seg,) = _build(afk, windows, tabs, end=300)

    assert seg.top_windows()[0].site == "docs.google.com"


def test_hourly_active_splits_across_hour_boundaries():
    segments = _build(_afk_run(3000, 4200, "active"), end=8000)

    buckets = hourly_active(segments, start=0, hours=2)

    assert round(buckets[0]) == 600 and round(buckets[1]) == 595  # last row: 4185 + 10s


def test_live_last_row_runs_until_now():
    afk = _afk_run(0, 300, "active")

    (seg,) = _build(afk, end=330)  # "now" is 45s after the last row

    assert round(seg.end) == 330
