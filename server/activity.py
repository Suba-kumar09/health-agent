"""Turns a device's raw agent events into the timeline the dashboard shows.

Three event streams feed it:
  - `afk`            {"state": "active" | "afk" | "locked"}  -- is someone at the keyboard
  - `window_watcher` {"app": "chrome.exe", "title": "..."}   -- the foreground window
  - `browser_bridge` {"url": "...", "title": "..."}           -- the active browser tab

Each stream is a series of "this is now the case" rows, so a row is treated
as lasting until the next row of the same stream (unless the gap is so long
the agent clearly wasn't running -- then only its own recorded duration
counts). Active time is then split by what was on screen: a window/tab that
matches a distraction keyword (and no exempt keyword, same rule as
server/goals.py) turns that slice into "distraction". Adjacent slices of the
same state merge into one segment, and each segment remembers which windows
were on screen and for how long.
"""
from __future__ import annotations

import bisect
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.goals import _matches_keyword
from server.models import Event

STATES = ("active", "distraction", "idle", "locked")

# A row counts until the next row, but never across a gap longer than this --
# a longer gap means the agent was stopped or the machine was off.
_MAX_CARRY_SECS = 120.0
# Same-state slices closer together than this merge into one segment.
_MERGE_GAP_SECS = 90.0
# A distraction slice shorter than this (a quick glance at a tab) stays
# "active" so the timeline isn't shredded into slivers. It still counts as a
# flagged window in the window list.
_MIN_DISTRACTION_SECS = 20.0
# A pause shorter than this between bursts of activity (reading, thinking,
# a quick call) counts as still working. The agent flags "no input" after
# ~30s, so without this a normal working hour shows as dozens of idle slivers.
_MIN_IDLE_SECS = 120.0

_APP_NAMES = {
    "chrome.exe": "Chrome",
    "msedge.exe": "Edge",
    "firefox.exe": "Firefox",
    "brave.exe": "Brave",
    "opera.exe": "Opera",
    "code.exe": "VS Code",
    "windowsterminal.exe": "Terminal",
    "cmd.exe": "Command Prompt",
    "powershell.exe": "PowerShell",
    "explorer.exe": "File Explorer",
    "slack.exe": "Slack",
    "teams.exe": "Teams",
    "ms-teams.exe": "Teams",
    "outlook.exe": "Outlook",
    "excel.exe": "Excel",
    "winword.exe": "Word",
    "powerpnt.exe": "PowerPoint",
    "figma.exe": "Figma",
    "notion.exe": "Notion",
    "zoom.exe": "Zoom",
    "spotify.exe": "Spotify",
    "whatsapp.exe": "WhatsApp",
    "notepad.exe": "Notepad",
}
_BROWSERS = {"Chrome", "Edge", "Firefox", "Brave", "Opera"}
# The app's own name at the end of a window title -- redundant, since the app
# is shown separately. Browsers first, then common desktop apps.
_APP_SUFFIX = re.compile(
    r"\s+[-–—]\s+("
    r"Google Chrome|Microsoft​? Edge|Mozilla Firefox|Brave|Opera|"
    r"Visual Studio Code|Notepad|File Explorer|Microsoft Teams|Slack|Figma|Notion|Zoom Workplace|"
    r"Word|Excel|PowerPoint|Outlook"
    r")\s*$",
    re.IGNORECASE,
)
_TAB_COUNT_PREFIX = re.compile(r"^\(\d+\)\s+")
# Status glyphs some apps put in front of the title -- a terminal's spinner
# ("✳ ", "◐ "), VS Code's unsaved dot ("● ") -- that would otherwise split
# one window into several rows as the glyph changes.
_LEADING_GLYPHS = re.compile(r"^[^\w(\[\"'.#@/\\]+\s*")

_SITE_NAMES = {"youtube": "YouTube", "tiktok": "TikTok", "prime video": "Prime Video", "hotstar": "Hotstar"}


def app_display_name(app: str | None) -> str:
    if not app:
        return "Browser"
    key = app.strip().lower()
    if key in _APP_NAMES:
        return _APP_NAMES[key]
    base = re.sub(r"\.exe$", "", app.strip(), flags=re.IGNORECASE)
    return base[:1].upper() + base[1:] if base else "Unknown app"


def clean_title(title: str | None) -> str:
    """"(3) Funny cats - YouTube - Google Chrome" -> "Funny cats - YouTube"."""
    if not title:
        return ""
    title = _APP_SUFFIX.sub("", title.strip())
    title = _TAB_COUNT_PREFIX.sub("", title)
    return _LEADING_GLYPHS.sub("", title) or title


def site_of(url: str | None) -> str | None:
    if not url:
        return None
    host = urlparse(url if "//" in url else "//" + url).hostname or ""
    return host[4:] if host.startswith("www.") else (host or None)


def site_display_name(keyword: str) -> str:
    return _SITE_NAMES.get(keyword, keyword.title())


def distraction_keyword(data: dict, keywords: list[str], exempt_keywords: list[str]) -> str | None:
    """The keyword a window matched, or None if it isn't a distraction (no
    match, or an exempt keyword like "lecture" also matched)."""
    if _matches_keyword(data, exempt_keywords):
        return None
    haystack = " ".join(str(data.get(f, "")) for f in ("title", "url", "app")).lower()
    for keyword in keywords:
        if keyword in haystack:
            return keyword
    return None


@dataclass
class Window:
    app: str
    title: str
    site: str | None
    flag: str | None  # matched distraction keyword


@dataclass
class WindowTotal:
    app: str
    title: str
    site: str | None
    flag: str | None
    secs: float = 0.0


@dataclass
class Segment:
    state: str
    start: float
    end: float
    windows: dict[tuple[str, str], WindowTotal] = field(default_factory=dict)

    @property
    def secs(self) -> float:
        return self.end - self.start

    def add(self, window: Window | None, secs: float) -> None:
        if window is None or secs <= 0:
            return
        key = (window.app, window.title)
        total = self.windows.get(key)
        if total is None:
            total = self.windows[key] = WindowTotal(window.app, window.title, window.site, window.flag)
        total.secs += secs

    def top_windows(self) -> list[WindowTotal]:
        return sorted(self.windows.values(), key=lambda w: w.secs, reverse=True)


@dataclass
class DeviceEvents:
    afk: list[Event]
    windows: list[Event]
    tabs: list[Event]


def load_events(session: Session, device_ids: Iterable[str], start: float, end: float) -> DeviceEvents:
    device_ids = list(device_ids)
    if not device_ids:
        return DeviceEvents([], [], [])
    # Look back a little so the row that was already in effect at `start` is included.
    rows = (
        session.execute(
            select(Event)
            .where(
                Event.device_id.in_(device_ids),
                Event.collector.in_(("afk", "window_watcher", "browser_bridge")),
                Event.ts >= start - _MAX_CARRY_SECS,
                Event.ts < end,
            )
            .order_by(Event.ts)
        )
        .scalars()
        .all()
    )
    by = {"afk": [], "window_watcher": [], "browser_bridge": []}
    for row in rows:
        by[row.collector].append(row)
    return DeviceEvents(by["afk"], by["window_watcher"], by["browser_bridge"])


def _spans(rows: list[Event], end: float) -> list[tuple[float, float, Event]]:
    """Each row lasts until the next row when that comes soon after. When the
    next row is far away (the agent was stopped in between) -- or there is no
    next row and this one isn't recent -- only the row's own recorded
    duration counts, so time the agent wasn't running is never filled in."""
    spans = []
    for i, row in enumerate(rows):
        own_end = row.ts + (row.duration or 0.0)
        nxt = rows[i + 1].ts if i + 1 < len(rows) else end
        stop = nxt if nxt - row.ts <= _MAX_CARRY_SECS else own_end
        stop = min(stop, nxt, end)
        if stop > row.ts:
            spans.append((row.ts, stop, row))
    return spans


def _tab_sites(tabs: list[Event]) -> dict[str, str]:
    sites: dict[str, str] = {}
    for tab in tabs:
        title = clean_title(tab.data.get("title")).lower()
        site = site_of(tab.data.get("url"))
        if title and site:
            sites[title] = site
    return sites


def _to_window(data: dict, tab_sites: dict[str, str], keywords: list[str], exempt: list[str]) -> Window:
    app = app_display_name(data.get("app"))
    title = clean_title(data.get("title")) or site_of(data.get("url")) or app
    site = site_of(data.get("url")) or (tab_sites.get(title.lower()) if app in _BROWSERS else None)
    probe = {"title": title, "url": data.get("url") or site or "", "app": data.get("app") or ""}
    return Window(app=app, title=title, site=site, flag=distraction_keyword(probe, keywords, exempt))


def build_segments(
    events: DeviceEvents, start: float, end: float, keywords: list[str], exempt_keywords: list[str]
) -> list[Segment]:
    tab_sites = _tab_sites(events.tabs)
    # Without the window watcher (disabled in config.toml), fall back to browser tabs.
    window_rows = events.windows or events.tabs
    window_spans = [
        (s, e, _to_window(row.data or {}, tab_sites, keywords, exempt_keywords))
        for s, e, row in _spans(window_rows, end)
    ]
    window_starts = [s for s, _, _ in window_spans]

    pieces: list[tuple[str, float, float, Window | None]] = []

    def overlapping(a0: float, a1: float):
        i = max(0, bisect.bisect_right(window_starts, a0) - 1)
        while i < len(window_spans) and window_spans[i][0] < a1:
            ws, we, window = window_spans[i]
            lo, hi = max(a0, ws), min(a1, we)
            if hi > lo:
                yield lo, hi, window
            i += 1

    for a0, a1, row in _spans(events.afk, end):
        a0, a1 = max(a0, start), min(a1, end)
        if a1 <= a0:
            continue
        raw = (row.data or {}).get("state")
        if raw == "locked":
            pieces.append(("locked", a0, a1, None))
        elif raw != "active":
            covered = False
            for lo, hi, window in overlapping(a0, a1):
                pieces.append(("idle", lo, hi, window))
                covered = True
            if not covered:
                pieces.append(("idle", a0, a1, None))
        else:
            cursor = a0
            for lo, hi, window in overlapping(a0, a1):
                if lo > cursor:
                    pieces.append(("active", cursor, lo, None))
                pieces.append(("distraction" if window.flag else "active", lo, hi, window))
                cursor = hi
            if cursor < a1:
                pieces.append(("active", cursor, a1, None))

    segments: list[Segment] = []
    for state, lo, hi, window in pieces:
        last = segments[-1] if segments else None
        if last is not None and last.state == state and lo - last.end <= _MERGE_GAP_SECS:
            last.end = max(last.end, hi)
        else:
            last = Segment(state=state, start=lo, end=hi)
            segments.append(last)
        last.add(window, hi - lo)

    # Only now, with afk rows (each just 5-15s) merged, is a distraction's
    # real length known: a brief glance at a flagged tab stays "active".
    for seg in segments:
        if seg.state == "distraction" and seg.secs < _MIN_DISTRACTION_SECS:
            seg.state = "active"
    segments = _merge_adjacent(segments)

    # Short pauses *between* activity count as working. A short idle at the
    # very start or end (nothing active on that side yet) stays idle.
    for i, seg in enumerate(segments):
        if seg.state != "idle" or seg.secs >= _MIN_IDLE_SECS:
            continue
        before = segments[i - 1] if i > 0 else None
        after = segments[i + 1] if i + 1 < len(segments) else None
        if (
            before is not None
            and after is not None
            and before.state in ("active", "distraction")
            and after.state in ("active", "distraction")
            and seg.start - before.end <= _MERGE_GAP_SECS
            and after.start - seg.end <= _MERGE_GAP_SECS
        ):
            seg.state = "active"
    return _merge_adjacent(segments)


def _merge_adjacent(segments: list[Segment]) -> list[Segment]:
    merged: list[Segment] = []
    for seg in segments:
        last = merged[-1] if merged else None
        if last is not None and last.state == seg.state and seg.start - last.end <= _MERGE_GAP_SECS:
            last.end = max(last.end, seg.end)
            for w in seg.windows.values():
                last.add(Window(w.app, w.title, w.site, w.flag), w.secs)
        else:
            merged.append(seg)
    return merged


def state_totals(segments: list[Segment]) -> dict[str, float]:
    totals = {state: 0.0 for state in STATES}
    for seg in segments:
        totals[seg.state] += seg.secs
    return totals


def window_totals(segments: list[Segment], include_idle: bool = False) -> list[WindowTotal]:
    """Every window/tab used across the segments, longest first. Idle time is
    excluded by default -- a window left open while away wasn't "used"."""
    merged: dict[tuple[str, str], WindowTotal] = {}
    for seg in segments:
        if seg.state == "locked" or (seg.state == "idle" and not include_idle):
            continue
        for key, w in seg.windows.items():
            total = merged.get(key)
            if total is None:
                total = merged[key] = WindowTotal(w.app, w.title, w.site, w.flag)
            total.secs += w.secs
    return sorted(merged.values(), key=lambda w: w.secs, reverse=True)


def hourly_active(segments: list[Segment], start: float, hours: int) -> list[float]:
    """Seconds of active + distraction time in each hour-long bucket from `start`."""
    buckets = [0.0] * hours
    for seg in segments:
        if seg.state not in ("active", "distraction"):
            continue
        lo = seg.start
        while lo < seg.end:
            idx = int((lo - start) // 3600)
            bucket_end = start + (idx + 1) * 3600
            hi = min(seg.end, bucket_end)
            if 0 <= idx < hours:
                buckets[idx] += hi - lo
            lo = hi
    return buckets


def latest_window(events: DeviceEvents, keywords: list[str], exempt_keywords: list[str]) -> Window | None:
    rows = events.windows or events.tabs
    if not rows:
        return None
    return _to_window(rows[-1].data or {}, _tab_sites(events.tabs), keywords, exempt_keywords)
