"""Mint enrollment codes and manage employees and their dashboard logins, run
directly against DATABASE_URL.

An enrollment code is pasted into the agent's enrollment flow
(agent.sync.enroll.enroll()); an employee's system_name must match the
agent's platform.node() hostname for enrollment to succeed (see
server.auth.enroll_device). `set-login` gives an employee a dashboard
password and role -- this is also how the first admin is created.

Usage:
    python -m server.admin_cli mint-code [--issued-for NAME] [--ttl-hours N]
    python -m server.admin_cli add-employee --name NAME --system-name SYSTEM_NAME [--email EMAIL]
    python -m server.admin_cli set-login --system-name SYSTEM_NAME [--role admin|employee] [--email EMAIL]
    python -m server.admin_cli list-employees
"""
from __future__ import annotations

import argparse
import getpass

from sqlalchemy import delete, func, select

from server.auth import mint_enrollment_code, resolve_employee_by_system_name
from server.config import get_settings
from server.dashboard_auth import ROLES, hash_password
from server.db import session_scope
from server.models import DashboardSession, Employee

MIN_PASSWORD_LENGTH = 8


def mint_code(issued_for: str | None, ttl_hours: int | None) -> str:
    settings = get_settings()
    ttl = ttl_hours if ttl_hours is not None else settings.enrollment_code_ttl_hours
    with session_scope() as session:
        code = mint_enrollment_code(session, ttl_hours=ttl, issued_for=issued_for)
        return code.code


def _check_email_free(session, email: str, employee_id: str | None = None) -> None:
    other = session.execute(select(Employee).where(func.lower(Employee.email) == email.lower())).scalars().first()
    if other is not None and other.employee_id != employee_id:
        raise SystemExit(f"the email '{email}' already belongs to '{other.name}'")


def add_employee(name: str, system_name: str, email: str | None = None) -> str:
    with session_scope() as session:
        existing = resolve_employee_by_system_name(session, system_name)
        if existing is not None:
            raise SystemExit(f"a system named '{system_name}' is already registered to '{existing.name}'")
        if email:
            _check_email_free(session, email)
        employee = Employee(name=name, system_name=system_name, email=email or None)
        session.add(employee)
        session.flush()
        return employee.employee_id


def set_login(system_name: str, password: str | None, role: str | None, email: str | None) -> str:
    """Sets (or resets) an employee's dashboard password, and optionally
    their role/email. Resetting a password signs out their existing sessions."""
    with session_scope() as session:
        employee = resolve_employee_by_system_name(session, system_name)
        if employee is None:
            raise SystemExit(f"no employee is registered with system name '{system_name}' (use add-employee first)")
        if password is not None:
            if len(password) < MIN_PASSWORD_LENGTH:
                raise SystemExit(f"the password must be at least {MIN_PASSWORD_LENGTH} characters")
            employee.password_hash = hash_password(password)
            session.execute(delete(DashboardSession).where(DashboardSession.employee_id == employee.employee_id))
        if role is not None:
            employee.role = role
        if email is not None:
            _check_email_free(session, email, employee.employee_id)
            employee.email = email or None
        return f"{employee.name} ({employee.system_name}): role={employee.role}, email={employee.email or '-'}"


def list_employees() -> list[tuple[str, str, str, str, str, bool]]:
    """Returns plain tuples rather than Employee objects -- session_scope()
    closes the session before this returns, and SQLAlchemy's default
    expire_on_commit leaves any attribute access on a detached Employee
    instance raising DetachedInstanceError."""
    with session_scope() as session:
        rows = session.execute(select(Employee).order_by(Employee.name)).scalars()
        return [
            (e.employee_id, e.name, e.system_name, e.role, e.email or "-", e.password_hash is not None) for e in rows
        ]


def _prompt_password() -> str:
    first = getpass.getpass("New dashboard password: ")
    second = getpass.getpass("Repeat the password: ")
    if first != second:
        raise SystemExit("the two passwords don't match")
    return first


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
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
    add_employee_parser.add_argument("--email", default=None, help="Optional email, usable as a dashboard login")

    login_parser = subparsers.add_parser(
        "set-login", help="Set an employee's dashboard password (prompted), and optionally their role/email"
    )
    login_parser.add_argument("--system-name", required=True, help="The employee's registered system name")
    login_parser.add_argument("--role", choices=ROLES, default=None, help="admin sees the whole organization")
    login_parser.add_argument("--email", default=None, help="Email they can log in with (\"\" to clear)")
    login_parser.add_argument(
        "--keep-password", action="store_true", help="Only change role/email, don't set a new password"
    )

    subparsers.add_parser("list-employees", help="List registered employees and their dashboard access")

    args = parser.parse_args()

    if args.command == "mint-code":
        print(mint_code(issued_for=args.issued_for, ttl_hours=args.ttl_hours))
    elif args.command == "add-employee":
        employee_id = add_employee(name=args.name, system_name=args.system_name, email=args.email)
        print(f"registered {args.name!r} ({args.system_name}) as employee_id={employee_id}")
    elif args.command == "set-login":
        password = None if args.keep_password else _prompt_password()
        print("updated " + set_login(args.system_name, password, args.role, args.email))
    elif args.command == "list-employees":
        for employee_id, name, system_name, role, email, has_password in list_employees():
            login = "can log in" if has_password else "no password yet"
            print(f"{employee_id}\t{name}\t{system_name}\t{role}\t{email}\t{login}")


if __name__ == "__main__":
    main()
