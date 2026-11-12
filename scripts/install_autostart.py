"""Register (or remove) health-agent as a per-user autostart entry.

Dispatches on `sys.platform`:

- Windows: writes a value under
  HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run via `winreg`.
  Verified live on this machine (install/uninstall both confirmed).
- Linux: writes a user systemd unit to ~/.config/systemd/user/health-agent.service and
  runs `systemctl --user daemon-reload` + `enable`/`disable`. Written per the documented
  pattern but not live-verified in this environment (no Linux machine available yet).
- macOS: writes a launchd user-agent plist to ~/Library/LaunchAgents and runs
  `launchctl load`/`unload`. Written but unverified, same caveat CLAUDE.md already
  states for agent/platform/macos.py -- there is no machine to test this on.

By default this points the autostart entry at a packaged exe if one exists at
dist/health-agent-windowed.exe (Windows) or dist/health-agent (Linux/macOS), falling
back to `<python> -m agent.main` (using this venv's interpreter) if no packaged build
is found. Pass --exe-path to point at a specific build instead.

Usage:
    python scripts/install_autostart.py install
    python scripts/install_autostart.py install --exe-path dist/health-agent-windowed.exe
    python scripts/install_autostart.py uninstall
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_NAME = "HealthAgent"
UNIT_NAME = "health-agent.service"
LAUNCHD_LABEL = "com.health-agent.agent"


def _default_packaged_exe() -> Path:
    return REPO_ROOT / "dist" / ("health-agent-windowed.exe" if sys.platform == "win32" else "health-agent")


def resolve_command(exe_path: str | None) -> list[str]:
    """Picks what to launch: an explicit --exe-path, else a packaged build under
    dist/ if one exists, else `<this venv's python> -m agent.main`."""
    if exe_path:
        return [str(Path(exe_path).resolve())]
    packaged = _default_packaged_exe()
    if packaged.exists():
        return [str(packaged)]
    return [sys.executable, "-m", "agent.main"]


def install_windows(command: list[str]) -> None:
    import winreg

    value = subprocess.list2cmdline(command)
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, value)
    print(f"Installed: HKCU\\...\\Run\\{APP_NAME} = {value}")


def uninstall_windows() -> None:
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, APP_NAME)
        print(f"Removed HKCU\\...\\Run\\{APP_NAME}")
    except FileNotFoundError:
        print(f"HKCU\\...\\Run\\{APP_NAME} was not set -- nothing to remove")


def _systemd_unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / UNIT_NAME


def install_linux(command: list[str]) -> None:
    exec_start = subprocess.list2cmdline(command)
    unit_path = _systemd_unit_path()
    unit_path.parent.mkdir(parents=True, exist_ok=True)
    unit_path.write_text(
        "[Unit]\n"
        "Description=Health Agent (background monitoring)\n\n"
        "[Service]\n"
        f"ExecStart={exec_start}\n"
        "Restart=on-failure\n\n"
        "[Install]\n"
        "WantedBy=default.target\n",
        encoding="utf-8",
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", UNIT_NAME], check=True)
    print(f"Installed and enabled {unit_path}")


def uninstall_linux() -> None:
    subprocess.run(["systemctl", "--user", "disable", UNIT_NAME], check=False)
    unit_path = _systemd_unit_path()
    unit_path.unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    print(f"Removed {unit_path}")


def _launchd_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"


def install_macos(command: list[str]) -> None:
    """Written but UNVERIFIED -- no macOS machine available in this environment,
    same caveat as agent/platform/macos.py. Review before relying on this."""
    args_xml = "\n".join(f"        <string>{arg}</string>" for arg in command)
    plist_path = _launchd_plist_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        "    <key>Label</key>\n"
        f"    <string>{LAUNCHD_LABEL}</string>\n"
        "    <key>ProgramArguments</key>\n"
        "    <array>\n"
        f"{args_xml}\n"
        "    </array>\n"
        "    <key>RunAtLoad</key>\n"
        "    <true/>\n"
        "</dict>\n"
        "</plist>\n",
        encoding="utf-8",
    )
    subprocess.run(["launchctl", "load", str(plist_path)], check=True)
    print(f"Installed and loaded {plist_path} (unverified -- please confirm this actually works)")


def uninstall_macos() -> None:
    plist_path = _launchd_plist_path()
    subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
    plist_path.unlink(missing_ok=True)
    print(f"Unloaded and removed {plist_path}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    install_p = sub.add_parser("install", help="Register the agent to start automatically on login")
    install_p.add_argument(
        "--exe-path",
        default=None,
        help="Path to a packaged health-agent exe; defaults to a dist/ build if present, "
        "else falls back to `<python> -m agent.main`",
    )

    sub.add_parser("uninstall", help="Remove the autostart registration")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()

    if args.command == "install":
        command = resolve_command(args.exe_path)
        if sys.platform == "win32":
            install_windows(command)
        elif sys.platform == "darwin":
            install_macos(command)
        else:
            install_linux(command)
    elif args.command == "uninstall":
        if sys.platform == "win32":
            uninstall_windows()
        elif sys.platform == "darwin":
            uninstall_macos()
        else:
            uninstall_linux()


if __name__ == "__main__":
    main()
