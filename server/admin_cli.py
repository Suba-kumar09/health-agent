"""Mint a single-use enrollment code / manage employees, run directly against DATABASE_URL.

There's no dashboard or user-account system in this phase, so this CLI is the
only way to issue an enrollment code (paste the printed code into the agent's
enrollment flow, agent.sync.enroll.enroll()) or register the employees whose
machines are allowed to enroll (matched by system_name against the agent's
platform.node() hostname -- see server.auth.enroll_device).

Usage:
    python -m server.admin_cli mint-code [--issued-for NAME] [--ttl-hours N]
    python -m server.admin_cli add-employee --name NAME --system-name SYSTEM_NAME
    python -m server.admin_cli list-employees
"""
from __future__ import annotations

import argparse

from sqlalchemy import select

from server.auth import mint_enrollment_code, resolve_employee_by_system_name
from server.config import get_settings
from server.db import session_scope
from server.models import Employee


def mint_code(issued_for: str | None, ttl_hours: int | None) -> str:
    settings = get_settings()
    ttl = ttl_hours if ttl_hours is not None else settings.enrollment_code_ttl_hours
    with session_scope() as session:
        code = mint_enrollment_code(session, ttl_hours=ttl, issued_for=issued_for)
        return code.code


def add_employee(name: str, system_name: str) -> str:
    with session_scope() as session:
        existing = resolve_employee_by_system_name(session, system_name)
        if existing is not None:
            raise SystemExit(f"a system named '{system_name}' is already registered to '{existing.name}'")
        employee = Employee(name=name, system_name=system_name)
        session.add(employee)
        session.flush()
        return employee.employee_id


def list_employees() -> list[tuple[str, str, str]]:
    """Returns (employee_id, name, system_name) tuples rather than Employee
    objects -- session_scope() closes the session before this returns, and
    SQLAlchemy's default expire_on_commit leaves any attribute access on a
    detached Employee instance raising DetachedInstanceError."""
    with session_scope() as session:
        rows = session.execute(select(Employee).order_by(Employee.name)).scalars()
        return [(e.employee_id, e.name, e.system_name) for e in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    mint_parser = subparsers.add_parser("mint-code", help="Mint a new enrollment code")
    mint_parser.add_argument("--issued-for", default=None, help="Free-text label for who/what this code is for")
    mint_parser.add_argument("--ttl-hours", type=int, default=None, help="Expiry in hours (default from settings)")

    add_employee_parser = subparsers.add_parser(
        "add-employee", help="Register an employee's machine so it's allowed to enroll"
    )
    add_employee_parser.add_argument("--name", required=True, help="Employee's name")
    add_employee_parser.add_argument(
        "--system-name", required=True, help="Employee's machine hostname (matches the agent's platform.node())"
    )

    subparsers.add_parser("list-employees", help="List registered employees")

    args = parser.parse_args()

    if args.command == "mint-code":
        code = mint_code(issued_for=args.issued_for, ttl_hours=args.ttl_hours)
        print(code)
    elif args.command == "add-employee":
        employee_id = add_employee(name=args.name, system_name=args.system_name)
        print(f"registered {args.name!r} ({args.system_name}) as employee_id={employee_id}")
    elif args.command == "list-employees":
        for employee_id, name, system_name in list_employees():
            print(f"{employee_id}\t{name}\t{system_name}")


if __name__ == "__main__":
    main()
