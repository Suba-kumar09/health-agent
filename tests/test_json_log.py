import json

from agent.json_log import JsonEventLogger
from agent.storage import Event


def test_append_writes_one_json_line_per_event(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = JsonEventLogger(path)

    e1 = Event(collector="input_watcher", ts=1.0, duration=30.0, data={"keypress_count": 5})
    e2 = Event(collector="window_watcher", ts=2.0, duration=0.0, data={"app": "chrome.exe"})
    logger.append(e1)
    logger.append(e2)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    record1 = json.loads(lines[0])
    assert record1["collector"] == "input_watcher"
    assert record1["ts"] == 1.0
    assert record1["duration"] == 30.0
    assert record1["data"] == {"keypress_count": 5}
    assert record1["event_id"] == e1.event_id

    record2 = json.loads(lines[1])
    assert record2["collector"] == "window_watcher"
    assert record2["data"] == {"app": "chrome.exe"}


def test_append_is_plain_text_not_encrypted(tmp_path):
    path = tmp_path / "events.jsonl"
    logger = JsonEventLogger(path)
    logger.append(Event(collector="afk", ts=1.0, data={"state": "active"}))

    raw = path.read_text(encoding="utf-8")
    assert "active" in raw  # readable without any decryption step
