from agent.collectors.input_watcher import InputBucketAggregator


def make_agg(capture_mode="aggregate", bucket_seconds=30, start=1000.0):
    clock = {"t": start}
    agg = InputBucketAggregator(bucket_seconds, capture_mode, now_fn=lambda: clock["t"])
    return agg, clock


def test_counts_accumulate_within_bucket():
    agg, clock = make_agg()
    agg.on_key_press("a")
    agg.on_key_press("b")
    agg.on_click()
    agg.on_scroll()

    bucket = agg.force_flush(now=clock["t"])

    assert bucket.keypress_count == 2
    assert bucket.click_count == 1
    assert bucket.scroll_count == 1


def test_aggregate_mode_does_not_record_key_codes():
    agg, clock = make_agg(capture_mode="aggregate")
    agg.on_key_press("secret-password-char")

    data = agg.force_flush(now=clock["t"]).to_data(detailed=False)

    assert "key_codes" not in data
    assert data["keypress_count"] == 1


def test_detailed_mode_records_key_codes():
    agg, clock = make_agg(capture_mode="detailed")
    agg.on_key_press("x")
    agg.on_key_press("y")

    data = agg.force_flush(now=clock["t"]).to_data(detailed=True)

    assert data["key_codes"] == ["x", "y"]


def test_mouse_distance_accumulates_euclidean():
    agg, clock = make_agg()
    agg.on_move(0, 0)
    agg.on_move(3, 4)  # distance 5
    agg.on_move(3, 4 + 12)  # distance 12 more -> total 17

    bucket = agg.force_flush(now=clock["t"])

    assert bucket.mouse_dist_px == 17.0


def test_active_secs_counts_distinct_seconds_not_events():
    agg, clock = make_agg(bucket_seconds=30, start=1000.0)
    clock["t"] = 1000.2
    agg.on_key_press("a")
    clock["t"] = 1000.7
    agg.on_key_press("b")  # same integer second as above -> still 1 active sec
    clock["t"] = 1002.0
    agg.on_click()  # a different second -> 2 active secs

    bucket = agg.force_flush(now=clock["t"])

    assert bucket.to_data(detailed=False)["active_secs"] == 2


def test_maybe_flush_returns_none_before_bucket_elapses():
    agg, clock = make_agg(bucket_seconds=30, start=1000.0)
    agg.on_key_press("a")

    clock["t"] = 1010.0
    assert agg.maybe_flush(now=clock["t"]) is None


def test_maybe_flush_returns_bucket_once_elapsed_and_resets():
    agg, clock = make_agg(bucket_seconds=30, start=1000.0)
    agg.on_key_press("a")

    clock["t"] = 1031.0
    bucket = agg.maybe_flush(now=clock["t"])

    assert bucket is not None
    assert bucket.keypress_count == 1
    assert bucket.bucket_start == 1000.0

    # New bucket starts fresh at the flush time.
    agg.on_key_press("b")
    next_bucket = agg.force_flush(now=clock["t"])
    assert next_bucket.keypress_count == 1
    assert next_bucket.bucket_start == 1031.0


def test_idle_bucket_flushes_with_zero_counts():
    agg, clock = make_agg(bucket_seconds=30, start=1000.0)

    clock["t"] = 1031.0
    bucket = agg.maybe_flush(now=clock["t"])

    assert bucket is not None
    assert bucket.to_data(detailed=False) == {
        "keypress_count": 0,
        "click_count": 0,
        "scroll_count": 0,
        "mouse_dist_px": 0.0,
        "active_secs": 0,
    }
