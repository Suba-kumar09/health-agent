from agent.collectors.window_watcher import _window_state_key


def test_window_state_key_uses_app_and_title():
    assert _window_state_key({"app": "chrome.exe", "title": "GitHub"}) == ("chrome.exe", "GitHub")


def test_window_state_key_none_for_no_window():
    assert _window_state_key(None) is None
