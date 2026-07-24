from agent.config import Config


def test_default_config_has_sane_values():
    cfg = Config.default()
    assert cfg.agent.capture_mode == "aggregate"
    assert cfg.agent.sync_interval_secs == 5400
    assert cfg.privacy.encrypt_at_rest is True
    assert cfg.privacy.json_log_enabled is True
    assert cfg.reports.enabled is True
    assert cfg.reports.interval_secs == 15


def test_load_example_config(tmp_path):
    example = tmp_path / "config.toml"
    example.write_text(
        """
[agent]
device_id = "abc"
server_url = "https://example.com"
capture_mode = "detailed"

[sync]
max_batches_per_tick = 3
"""
    )
    cfg = Config.load(example)
    assert cfg.agent.device_id == "abc"
    assert cfg.agent.capture_mode == "detailed"
    assert cfg.sync.max_batches_per_tick == 3
