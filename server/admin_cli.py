"""Mint a single-use enrollment code, run directly against DATABASE_URL.

There's no dashboard or user-account system in this phase, so this CLI is the
only way to issue a code -- paste the printed code into the agent's enrollment
flow (agent.sync.enroll.enroll()).

Usage:
    python -m server.admin_cli mint-code [--issued-for NAME] [--ttl-hours N]
"""
from __future__ import annotations

import argparse

from server.auth import mint_enrollment_code
from server.config import get_settings
from server.db import session_scope


def mint_code(issued_for: str | None, ttl_hours: int | None) -> str:
    settings = get_settings()
    ttl = ttl_hours if ttl_hours is not None else settings.enrollment_code_ttl_hours
    with session_scope() as session:
        code = mint_enrollment_code(session, ttl_hours=ttl, issued_for=issued_for)
        return code.code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    mint_parser = subparsers.add_parser("mint-code", help="Mint a new enrollment code")
    mint_parser.add_argument("--issued-for", default=None, help="Free-text label for who/what this code is for")
    mint_parser.add_argument("--ttl-hours", type=int, default=None, help="Expiry in hours (default from settings)")

    args = parser.parse_args()

    if args.command == "mint-code":
        code = mint_code(issued_for=args.issued_for, ttl_hours=args.ttl_hours)
        print(code)


if __name__ == "__main__":
    main()
