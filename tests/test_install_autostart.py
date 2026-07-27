import sys
from pathlib import Path

import scripts.install_autostart as install_autostart
from scripts.install_autostart import resolve_command


def test_resolve_command_uses_explicit_exe_path(tmp_path):
    fake_exe = tmp_path / "fake-health-agent.exe"
    fake_exe.write_text("")

    command = resolve_command(str(fake_exe))

    assert command == [str(fake_exe.resolve())]


def test_resolve_command_falls_back_to_python_module_invocation(monkeypatch):
    monkeypatch.setattr(install_autostart, "_default_packaged_exe", lambda: Path("/does/not/exist"))

    command = resolve_command(None)

    assert command == [sys.executable, "-m", "agent.main"]


def test_resolve_command_prefers_packaged_exe_when_present(monkeypatch, tmp_path):
    packaged = tmp_path / "health-agent-windowed.exe"
    packaged.write_text("")
    monkeypatch.setattr(install_autostart, "_default_packaged_exe", lambda: packaged)

    command = resolve_command(None)

    assert command == [str(packaged)]
