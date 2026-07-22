from agent.collectors.coalescing import CoalescingStatePoller


def make_poller():
    events = []  # (info, ts) for new states
    extends = []  # (event_id, duration)

    def on_new_state(info, ts):
        event_id = f"evt-{len(events)}"
        events.append((event_id, info, ts))
        return event_id

    def on_extend(event_id, duration):
        extends.append((event_id, duration))

    poller = CoalescingStatePoller(
        state_key_fn=lambda info: info.get("k") if info else None,
        on_new_state=on_new_state,
        on_extend=on_extend,
    )
    return poller, events, extends


def test_first_poll_creates_new_state():
    poller, events, extends = make_poller()

    poller.poll({"k": "a"}, now=100.0)

    assert len(events) == 1
    assert events[0][1] == {"k": "a"}
    assert extends == []


def test_repeated_identical_state_extends_not_recreates():
    poller, events, extends = make_poller()
    poller.poll({"k": "a"}, now=100.0)

    poller.poll({"k": "a"}, now=105.0)
    poller.poll({"k": "a"}, now=110.0)

    assert len(events) == 1
    assert extends == [("evt-0", 5.0), ("evt-0", 10.0)]


def test_state_change_finalizes_and_creates_new():
    poller, events, extends = make_poller()
    poller.poll({"k": "a"}, now=100.0)
    poller.poll({"k": "a"}, now=105.0)

    poller.poll({"k": "b"}, now=110.0)

    assert len(events) == 2
    assert events[1][1] == {"k": "b"}
    # no extend call for the new state itself
    assert extends == [("evt-0", 5.0)]


def test_none_info_clears_current_state_without_creating_event():
    poller, events, extends = make_poller()
    poller.poll({"k": "a"}, now=100.0)

    poller.poll(None, now=105.0)

    assert len(events) == 1  # no new event for the None state
    assert extends == []

    # Coming back to the same key "a" after a None gap creates a fresh event
    # (not an extend of the old one) since the current state was cleared.
    poller.poll({"k": "a"}, now=110.0)
    assert len(events) == 2
