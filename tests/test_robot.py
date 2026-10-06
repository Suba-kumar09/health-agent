from __future__ import annotations

from agent.robot import (
    BUBBLE_MAX_CHARS,
    badge_icon,
    bubble_text,
    clamp_y,
    dock_position,
    eyes_open,
    mouth_height,
    mute_label,
)


def test_buddy_docks_on_the_right_edge_a_little_below_the_middle():
    # 1366x768 screen with a 48px taskbar -> work area 1366x720.
    x, y = dock_position((0, 0, 1366, 720), (360, 170), margin=6, fraction=0.55)
    assert x == 1366 - 360 - 6
    assert y == int(720 * 0.55 - 170 / 2)


def test_dock_position_never_goes_off_a_tiny_screen():
    assert dock_position((0, 0, 200, 100), (360, 170)) == (0, 0)


def test_dragging_is_kept_on_screen():
    area = (0, 0, 1366, 720)
    assert clamp_y(-50, area, 170) == 0
    assert clamp_y(900, area, 170) == 720 - 170
    assert clamp_y(300, area, 170) == 300


def test_bubble_text_keeps_short_text_and_collapses_spaces():
    assert bubble_text("  Take   a\nbreak! ") == "Take a break!"


def test_bubble_text_cuts_long_text_at_a_word():
    out = bubble_text("word " * 100)
    assert len(out) <= BUBBLE_MAX_CHARS
    assert out.endswith("…") and not out.endswith(" …")


def test_eyes_blink_briefly_and_regularly():
    frames = [eyes_open(f) for f in range(140)]
    assert frames.count(False) == 6  # two blinks of three frames
    assert frames[10] is True


def test_mouth_moves_only_while_speaking():
    assert {mouth_height(f, speaking=False) for f in range(20)} == {3.0}
    heights = {round(mouth_height(f, speaking=True), 1) for f in range(20)}
    assert len(heights) > 5 and max(heights) <= 10.0


def test_mute_button_says_what_a_click_will_do():
    assert mute_label(False).endswith("Mute") and not mute_label(False).endswith("Unmute")
    assert mute_label(True).endswith("Unmute")


def test_badge_shows_the_current_state():
    assert badge_icon(True) != badge_icon(False)
