from __future__ import annotations

import socket

from agent.single_instance import InstanceLock, port_is_free


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_second_lock_on_same_port_is_refused():
    port = _free_port()
    first, second = InstanceLock(port), InstanceLock(port)
    try:
        assert first.acquire() is True
        assert second.acquire() is False
    finally:
        first.release()
        second.release()


def test_lock_can_be_taken_again_after_release():
    port = _free_port()
    first = InstanceLock(port)
    assert first.acquire()
    first.release()
    second = InstanceLock(port)
    try:
        assert second.acquire() is True
    finally:
        second.release()


def test_acquire_is_idempotent_for_the_holder():
    lock = InstanceLock(_free_port())
    try:
        assert lock.acquire() and lock.acquire()
    finally:
        lock.release()


def test_port_is_free_detects_a_listener():
    port = _free_port()
    assert port_is_free(port) is True
    lock = InstanceLock(port)
    lock.acquire()
    try:
        assert port_is_free(port) is False
    finally:
        lock.release()
