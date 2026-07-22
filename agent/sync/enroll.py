from __future__ import annotations

import httpx

from agent.sync.api import EnrollRequest, EnrollResponse


class EnrollmentError(Exception):
    pass


def enroll(
    http_client: httpx.Client,
    server_url: str,
    enrollment_code: str,
    device_name: str,
    os_name: str,
    os_version: str,
) -> EnrollResponse:
    """Exchanges a one-time enrollment code for a device_id + device_token.

    The server side of POST /v1/enroll is out of Phase-1 scope (see docs/API.md)
    -- this client exists so the exchange is a one-line call once that endpoint
    is live, and so the contract has a real caller instead of just pydantic
    models nobody exercises.
    """
    request = EnrollRequest(
        enrollment_code=enrollment_code,
        device_name=device_name,
        os=os_name,
        os_version=os_version,
    )
    resp = http_client.post(f"{server_url.rstrip('/')}/v1/enroll", json=request.model_dump())
    if resp.status_code != 200:
        raise EnrollmentError(f"enroll failed: HTTP {resp.status_code} {resp.text}")
    return EnrollResponse.model_validate(resp.json())
