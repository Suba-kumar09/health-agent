from agent.config import Config


def test_default_config_has_sane_values():
    cfg = Config.default()
    assert cfg.agent.capture_mode == "aggregate"
    assert cfg.agent.sync_interval_secs == 5400
    assert cfg.privacy.encrypt_at_rest is True


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


def test_voice_defaults_and_overrides(tmp_path):
    assert Config.default().voice.enabled is True
    path = tmp_path / "config.toml"
    path.write_text('[voice]\nenabled = false\npitch = 8\nvoice_name = "Zira"\n')
    cfg = Config.load(path)
    assert (cfg.voice.enabled, cfg.voice.pitch, cfg.voice.voice_name, cfg.voice.robot) == (False, 8, "Zira", True)
