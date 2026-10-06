import httpx

from agent.sync.messages import MessagesPoller


def make_poller(transport, on_message, token="test-token"):
    client = httpx.Client(transport=transport)
    return MessagesPoller(
        http_client=client,
        server_url="https://ingest.test",
        token_provider=lambda: token,
        on_message=on_message,
    )


def test_delivers_each_pending_message():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-token"
        return httpx.Response(
            200,
            json={
                "messages": [
                    {"message_id": "m1", "text": "hello", "created_at": 1.0},
                    {"message_id": "m2", "text": "world", "created_at": 2.0},
                ]
            },
        )

    delivered = []
    poller = make_poller(httpx.MockTransport(handler), on_message=delivered.append)

    count = poller.poll_once()

    assert count == 2
    assert delivered == ["hello", "world"]


def test_no_messages_calls_nothing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"messages": []})

    delivered = []
    poller = make_poller(httpx.MockTransport(handler), on_message=delivered.append)

    assert poller.poll_once() == 0
    assert delivered == []


def test_unenrolled_device_skips_the_request():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not be called when unenrolled")

    delivered = []
    poller = make_poller(httpx.MockTransport(handler), on_message=delivered.append, token="unenrolled")

    assert poller.poll_once() == 0
    assert delivered == []


def test_non_200_response_is_ignored():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    delivered = []
    poller = make_poller(httpx.MockTransport(handler), on_message=delivered.append)

    assert poller.poll_once() == 0
    assert delivered == []


def test_network_error_is_ignored():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    delivered = []
    poller = make_poller(httpx.MockTransport(handler), on_message=delivered.append)

    assert poller.poll_once() == 0
    assert delivered == []


def _recording_handler(messages, ack_status=200):
    """Serves `messages` on GET .../pending and records every POST .../ack body."""
    acks: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            import json

            acks.append(json.loads(request.content)["message_ids"])
            return httpx.Response(ack_status, json={"acknowledged": 1})
        return httpx.Response(200, json={"messages": messages})

    return handler, acks


_TWO = [
    {"message_id": "m1", "text": "hello", "created_at": 1.0},
    {"message_id": "m2", "text": "world", "created_at": 2.0},
]


def test_acks_messages_after_showing_them():
    handler, acks = _recording_handler(_TWO)
    poller = make_poller(httpx.MockTransport(handler), on_message=lambda text: True)

    assert poller.poll_once() == 2
    assert acks == [["m1", "m2"]]


def test_callback_returning_none_counts_as_shown():
    handler, acks = _recording_handler(_TWO)
    poller = make_poller(httpx.MockTransport(handler), on_message=lambda text: None)

    poller.poll_once()

    assert acks == [["m1", "m2"]]


def test_failed_popup_is_not_acked_so_it_is_retried():
    handler, acks = _recording_handler(_TWO)
    poller = make_poller(httpx.MockTransport(handler), on_message=lambda text: text != "hello")

    assert poller.poll_once() == 1
    assert acks == [["m2"]]  # m1's popup failed -> left un-acked -> server re-sends it


def test_raising_callback_is_not_acked_and_does_not_stop_the_rest():
    def on_message(text):
        if text == "hello":
            raise RuntimeError("toast exploded")

    handler, acks = _recording_handler(_TWO)
    poller = make_poller(httpx.MockTransport(handler), on_message=on_message)

    assert poller.poll_once() == 1
    assert acks == [["m2"]]


def test_no_ack_request_when_nothing_was_shown():
    handler, acks = _recording_handler(_TWO)
    poller = make_poller(httpx.MockTransport(handler), on_message=lambda text: False)

    assert poller.poll_once() == 0
    assert acks == []


def test_failed_ack_does_not_repop_the_same_message():
    shown = []
    handler, acks = _recording_handler(_TWO, ack_status=500)
    poller = make_poller(httpx.MockTransport(handler), on_message=lambda text: shown.append(text) or True)

    poller.poll_once()
    poller.poll_once()  # server re-sent both because the ack failed

    assert shown == ["hello", "world"]  # popped once each, not twice
    assert acks == [["m1", "m2"], ["m1", "m2"]]  # but the ack is retried


def test_on_connected_fires_once_after_the_first_successful_poll():
    calls = []
    handler, _acks = _recording_handler([])
    client = httpx.Client(transport=httpx.MockTransport(handler))
    poller = MessagesPoller(
        http_client=client,
        server_url="https://ingest.test",
        token_provider=lambda: "t",
        on_message=lambda text: True,
        on_connected=lambda: calls.append(1),
    )

    poller.poll_once()
    poller.poll_once()

    assert calls == [1]


def test_on_connected_does_not_fire_while_the_server_is_down():
    calls = []

    def handler(request):
        raise httpx.ConnectError("down", request=request)

    poller = MessagesPoller(
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        server_url="https://ingest.test",
        token_provider=lambda: "t",
        on_message=lambda text: True,
        on_connected=lambda: calls.append(1),
    )

    poller.poll_once()

    assert calls == []
