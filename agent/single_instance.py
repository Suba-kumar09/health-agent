"""Machine-wide "only one of these may run" guard.

Two agents (or two servers running the orchestrator) on one machine each poll
and fire independently -- duplicate popups, or one process silently consuming
a message the other was meant to show. A localhost TCP port is used as the
lock because it is portable, needs no lock-file cleanup, and is released by the
OS automatically if the process crashes or is killed. Binding deliberately
avoids SO_REUSEADDR: on Windows that option lets a second process bind the
same port, which would defeat the whole guard.
"""
from __future__ import annotations

import socket

AGENT_LOCK_PORT = 47391
ORCHESTRATOR_LOCK_PORT = 47392


class InstanceLock:
    def __init__(self, port: int) -> None:
        self.port = port
        self._sock: socket.socket | None = None

    def acquire(self) -> bool:
        """True if this process now holds the lock, False if another does."""
        if self._sock is not None:
            return True
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", self.port))
            sock.listen(1)
        except OSError:
            sock.close()
            return False
        self._sock = sock
        return True

    def release(self) -> None:
        if self._sock is not None:
            self._sock.close()
            self._sock = None


def port_is_free(port: int, host: str = "0.0.0.0") -> bool:
    """True if nothing is currently listening on host:port."""
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        if probe.connect_ex((probe_host, port)) == 0:
            return False  # something is accepting connections there
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()
