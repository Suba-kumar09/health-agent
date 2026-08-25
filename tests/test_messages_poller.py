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
