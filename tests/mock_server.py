"""Throwaway mock ingest server fixture for integration tests.

Implements just enough of POST /v1/ingest to exercise the agent's uploader
end-to-end: auth check, idempotent dedup keyed on batch_id, and toggleable
failure injection (rate limiting / outages) for backlog-pacing tests.
"""
from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from agent.sync.api import IngestRequest


class MockIngestServer:
    def __init__(self, expected_token: str = "test-token") -> None:
        self.expected_token = expected_token
        self.seen_batch_ids: set[str] = set()
        self.seen_event_ids: set[str] = set()
        self.received_requests: list[IngestRequest] = []
        self.force_rate_limit = False
        self.retry_after = 1.0
        self.force_offline = False
        self.app = FastAPI()
        self._register_routes()

    def _register_routes(self) -> None:
        @self.app.post("/v1/ingest")
        async def ingest(request: Request, authorization: str = Header(default="")):
            if self.force_offline:
                raise HTTPException(status_code=503)

            if authorization != f"Bearer {self.expected_token}":
                raise HTTPException(status_code=401)

            if self.force_rate_limit:
                return JSONResponse(status_code=429, content={"retry_after": self.retry_after})

            body = await request.body()
            content_encoding = request.headers.get("content-encoding", "")
            if content_encoding == "gzip":
                import gzip

                body = gzip.decompress(body)

            payload = IngestRequest.model_validate_json(body)
            self.received_requests.append(payload)

            accepted: list[str] = []
            duplicates: list[str] = []
            for event in payload.events:
                if event.event_id in self.seen_event_ids:
                    duplicates.append(event.event_id)
                else:
                    self.seen_event_ids.add(event.event_id)
                    accepted.append(event.event_id)
            self.seen_batch_ids.add(payload.batch_id)

            return {"accepted": accepted, "duplicates": duplicates}
