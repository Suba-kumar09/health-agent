from __future__ import annotations

from agent.buddy_settings import BuddySettings


def test_settings_survive_a_restart_and_keep_other_keys(tmp_path):
    path = tmp_path / "buddy.json"
    first = BuddySettings(path)
    first.set("muted", True)
    first.set("hidden", True)
    first.set("y", 420)

    second = BuddySettings(path)
    assert (second.get("muted"), second.get("hidden"), second.get("y")) == (True, True, 420)


def test_missing_or_broken_file_means_defaults(tmp_path):
    assert BuddySettings(tmp_path / "nope.json").get("hidden", False) is False
    broken = tmp_path / "buddy.json"
    broken.write_text("[1, 2, 3]")  # valid JSON, wrong shape
    assert BuddySettings(broken).get("muted", False) is False


def test_in_memory_settings_work_without_a_file():
    s = BuddySettings()
    s.set("hidden", True)
    assert s.get("hidden") is True
