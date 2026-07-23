import time

import pytest

from agent.config import RetentionSection
from agent.crypto import FieldCipher
from agent.storage import Event, Storage, run_retention


@pytest.fixture
def storage(tmp_path):
    cipher = FieldCipher(FieldCipher.generate_key())
    s = Storage(tmp_path / "events.db", cipher=cipher)
    yield s
    s.close()


def test_append_and_read_back_decrypts(storage):
    e = Event(collector="input_watcher", ts=time.time(), data={"keypress_count": 5})
    storage.append(e)

    unsynced = storage.unassigned_unsynced(10)
    assert len(unsynced) == 1
    assert unsynced[0].data == {"keypress_count": 5}
    assert unsynced[0].event_id == e.event_id


def test_assign_batch_removes_from_unassigned_pool(storage):
    e1 = Event(collector="input_watcher", ts=1.0, data={})
    e2 = Event(collector="input_watcher", ts=2.0, data={})
    storage.append_many([e1, e2])

    storage.assign_batch([e1.event_id], "batch-1")

    unassigned = storage.unassigned_unsynced(10)
    assert [e.event_id for e in unassigned] == [e2.event_id]
    assert storage.pending_batch_ids() == ["batch-1"]


def test_mark_synced_clears_pending_batch(storage):
    e1 = Event(collector="input_watcher", ts=1.0, data={})
    storage.append(e1)
    storage.assign_batch([e1.event_id], "batch-1")

    storage.mark_synced([e1.event_id])

    assert storage.pending_batch_ids() == []
    assert storage.count_unsynced() == 0


def test_events_for_batch_returns_assigned_rows(storage):
    e1 = Event(collector="window_watcher", ts=1.0, data={"app": "vscode"})
    e2 = Event(collector="window_watcher", ts=2.0, data={"app": "chrome"})
    storage.append_many([e1, e2])
    storage.assign_batch([e1.event_id, e2.event_id], "batch-xyz")

    events = storage.events_for_batch("batch-xyz")

    assert {e.data["app"] for e in events} == {"vscode", "chrome"}


def test_extend_duration_updates_unbatched_unsynced_event(storage):
    e = Event(collector="window_watcher", ts=1.0, duration=0.0, data={"app": "vscode"})
    storage.append(e)

    updated = storage.extend_duration(e.event_id, 5.0)

    assert updated is True
    row = storage.unassigned_unsynced(10)[0]
    assert row.duration == 5.0


def test_extend_duration_refuses_once_batched(storage):
    e = Event(collector="window_watcher", ts=1.0, duration=0.0, data={"app": "vscode"})
    storage.append(e)
    storage.assign_batch([e.event_id], "batch-1")

    updated = storage.extend_duration(e.event_id, 5.0)

    assert updated is False


def test_purge_synced_deletes_old_synced_events_only(storage):
    old = Event(collector="afk", ts=time.time() - 10_000, data={})
    storage.append(old)
    storage.assign_batch([old.event_id], "b1")
    storage.mark_synced([old.event_id])

    recent = Event(collector="afk", ts=time.time(), data={})
    storage.append(recent)

    deleted = storage.purge_synced(older_than_secs=100)

    assert deleted == 1
    assert storage.count_unsynced() == 1


def test_run_retention_delete_after_sync_uses_grace_secs(storage):
    old = Event(collector="afk", ts=time.time() - 10_000, data={})
    storage.append(old)
    storage.assign_batch([old.event_id], "b1")
    storage.mark_synced([old.event_id])

    cfg = RetentionSection(mode="delete_after_sync", grace_secs=100, keep_days=30)
    deleted = run_retention(storage, cfg)

    assert deleted == 1


def test_run_retention_keep_days_uses_keep_days_not_grace_secs(storage):
    old = Event(collector="afk", ts=time.time() - 100, data={})
    storage.append(old)
    storage.assign_batch([old.event_id], "b1")
    storage.mark_synced([old.event_id])

    # grace_secs alone would delete this (100s old > 50s grace), but keep_days=30
    # should protect it since it's nowhere near 30 days old.
    cfg = RetentionSection(mode="keep_days", grace_secs=50, keep_days=30)
    deleted = run_retention(storage, cfg)

    assert deleted == 0
