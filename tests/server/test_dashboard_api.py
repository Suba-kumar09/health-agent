from __future__ import annotations

import time
import uuid
from datetime import datetime

import pytest
from sqlalchemy import Column, MetaData, String, Table, create_engine, inspect

from server.dashboard_auth import hash_password, verify_password
from server.db import add_missing_sqlite_columns
from server.models import DashboardSession, Device, Employee, Event, Goal, Message
from server.routes import auth as auth_routes

PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    auth_routes._failures.clear()
    yield
    auth_routes._failures.clear()


def _employee(db, name, system_name, role="employee", email=None, password=PASSWORD) -> Employee:
    # Low iteration count keeps the suite fast; verify_password reads the
    # count back out of the stored hash, so this is the real code path.
    e = Employee(
        name=name,
        system_name=system_name,
        role=role,
        email=email,
        password_hash=hash_password(password, iterations=1000) if password else None,
    )
    db.add(e)
    db.commit()
    return e


def _device(db, employee, last_seen=None) -> Device:
    d = Device(
        device_token_hash=uuid.uuid4().hex,
        device_name=employee.system_name,
        os="Windows",
        os_version="11",
        employee_id=employee.employee_id,
        last_seen_at=time.time() if last_seen is None else last_seen,
    )
    db.add(d)
    db.commit()
    return d


def _event(db, device, collector, ts, duration=0.0, **data):
    db.add(Event(event_id=str(uuid.uuid4()), device_id=device.device_id, collector=collector, ts=ts,
                 duration=duration, data=data, batch_id="b"))


def _active_minutes(db, device, start, minutes, app="Code.exe", title="main.py - project"):
    t = start
    while t < start + minutes * 60:
        _event(db, device, "afk", t, 10, state="active")
        t += 15
    _event(db, device, "window_watcher", start, minutes * 60, app=app, title=title)
    db.commit()


def _login(client, login, password=PASSWORD):
    return client.post("/v1/auth/login", json={"login": login, "password": password})


def _auth(client, login) -> dict:
    token = _login(client, login).json()["token"]
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- passwords


def test_password_hash_round_trip():
    stored = hash_password("s3cret-pass", iterations=1000)
    assert stored.startswith("pbkdf2_sha256$1000$")
    assert verify_password("s3cret-pass", stored)
    assert not verify_password("wrong", stored)
    assert not verify_password("anything", None)
    assert not verify_password("anything", "garbage")


# ---------------------------------------------------------------- login


def test_login_with_system_name_or_email_case_insensitive(client, db_session):
    _employee(db_session, "Priya", "DESKTOP-PRIYA", email="priya@example.com")

    by_host = _login(client, "desktop-priya")
    by_email = _login(client, "PRIYA@example.com")

    assert by_host.status_code == 200 and by_email.status_code == 200
    assert by_host.json()["account"]["name"] == "Priya"
    assert by_host.json()["account"]["role"] == "employee"


def test_wrong_password_unknown_login_and_no_password_all_look_the_same(client, db_session):
    _employee(db_session, "Priya", "DESKTOP-PRIYA")
    _employee(db_session, "New Hire", "DESKTOP-NEW", password=None)

    responses = [_login(client, "DESKTOP-PRIYA", "wrong"), _login(client, "nobody"), _login(client, "DESKTOP-NEW", "x")]

    assert {r.status_code for r in responses} == {401}
    assert len({r.json()["detail"] for r in responses}) == 1


def test_repeated_wrong_passwords_are_throttled(client, db_session):
    _employee(db_session, "Priya", "DESKTOP-PRIYA")
    for _ in range(5):
        assert _login(client, "DESKTOP-PRIYA", "wrong").status_code == 401

    assert _login(client, "DESKTOP-PRIYA").status_code == 429  # even the right password waits


def test_me_and_logout_revokes_the_session(client, db_session):
    _employee(db_session, "Priya", "DESKTOP-PRIYA")
    headers = _auth(client, "DESKTOP-PRIYA")

    assert client.get("/v1/auth/me", headers=headers).json()["name"] == "Priya"
    assert client.post("/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/v1/auth/me", headers=headers).status_code == 401
    assert db_session.query(DashboardSession).count() == 0


def test_expired_session_is_rejected(client, db_session):
    _employee(db_session, "Priya", "DESKTOP-PRIYA")
    headers = _auth(client, "DESKTOP-PRIYA")
    db_session.query(DashboardSession).update({DashboardSession.expires_at: time.time() - 1})
    db_session.commit()

    assert client.get("/v1/me/today", headers=headers).status_code == 401


def test_a_device_token_cannot_open_the_dashboard(client, db_session):
    assert client.get("/v1/me/today", headers={"Authorization": "Bearer some-device-token"}).status_code == 401


# ---------------------------------------------------------------- my dashboard


def test_today_requires_login(client):
    assert client.get("/v1/me/today").status_code == 401
    assert client.get("/v1/me/week").status_code == 401


def test_today_shows_only_my_own_activity_with_window_titles(client, db_session):
    me = _employee(db_session, "Priya", "DESKTOP-PRIYA")
    other = _employee(db_session, "Farhan", "DESKTOP-FARHAN")
    now = time.time()
    _active_minutes(db_session, _device(db_session, me), now - 600, 10, app="chrome.exe",
                    title="Survey results - Google Sheets - Google Chrome")
    _active_minutes(db_session, _device(db_session, other), now - 600, 10, title="secret-project.py")

    body = client.get("/v1/me/today", headers=_auth(client, "DESKTOP-PRIYA")).json()

    assert body["employee_name"] == "Priya"
    assert body["workday_secs"] == 8 * 3600  # WORKDAY_HOURS default
    assert body["status"]["status"] == "active"
    assert body["totals"]["active"] > 500
    titles = [w["title"] for s in body["segments"] for w in s["windows"]]
    assert titles == ["Survey results - Google Sheets"]
    assert body["apps"][0]["app"] == "Chrome"


def test_hours_add_up_to_the_day_and_list_only_their_own_windows(client, db_session):
    me = _employee(db_session, "Priya", "DESKTOP-PRIYA")
    device = _device(db_session, me)
    now = time.time()
    this_hour = datetime.fromtimestamp(now).replace(minute=0, second=0, microsecond=0).timestamp()
    if now - this_hour < 300 or this_hour - 3600 < datetime.fromtimestamp(now).replace(hour=0, minute=0).timestamp():
        pytest.skip("too close to the start of an hour/day for a two-hour fixture")
    # 20 min of VS Code ending 10 min before this hour, then Excel from the hour start on.
    _active_minutes(db_session, device, this_hour - 1800, 20, app="Code.exe", title="main.py - app")
    _active_minutes(db_session, device, this_hour, (now - this_hour) / 60, app="excel.exe", title="Budget.xlsx - Excel")

    body = client.get("/v1/me/today", headers=_auth(client, "DESKTOP-PRIYA")).json()

    hours = {h["hour_start"]: h for h in body["hours"]}
    assert [w["title"] for w in hours[this_hour - 3600]["windows"]] == ["main.py - app"]
    assert [w["title"] for w in hours[this_hour]["windows"]] == ["Budget.xlsx"]
    for state in ("active", "distraction", "idle", "locked"):
        assert abs(sum(h["totals"][state] for h in body["hours"]) - body["totals"][state]) < 1


def test_distraction_segment_carries_the_tab_title(client, db_session):
    me = _employee(db_session, "Priya", "DESKTOP-PRIYA")
    now = time.time()
    _active_minutes(db_session, _device(db_session, me), now - 300, 5, app="chrome.exe",
                    title="Top 10 IPL finishes - YouTube - Google Chrome")

    body = client.get("/v1/me/today", headers=_auth(client, "DESKTOP-PRIYA")).json()

    assert body["status"]["status"] == "distraction"
    seg = [s for s in body["segments"] if s["state"] == "distraction"][0]
    assert seg["windows"][0] == {**seg["windows"][0], "title": "Top 10 IPL finishes - YouTube", "flag": "youtube"}


def test_week_has_seven_days_ending_today(client, db_session):
    _employee(db_session, "Priya", "DESKTOP-PRIYA")

    days = client.get("/v1/me/week", headers=_auth(client, "DESKTOP-PRIYA")).json()

    assert len(days) == 7
    assert days[-1]["date"] == time.strftime("%Y-%m-%d")


def test_set_goal_then_see_it_today(client, db_session):
    _employee(db_session, "Priya", "DESKTOP-PRIYA")
    headers = _auth(client, "DESKTOP-PRIYA")

    resp = client.post("/v1/me/goal", headers=headers, json={"text": "Finish the Q3 report", "hours": 3})

    assert resp.status_code == 200
    assert client.get("/v1/me/today", headers=headers).json()["goal"]["text"] == "Finish the Q3 report"
    assert db_session.query(Goal).count() == 1
    assert client.post("/v1/me/goal", headers=headers, json={"text": "", "hours": 3}).status_code == 422


# ---------------------------------------------------------------- admin


def test_admin_endpoints_need_an_admin(client, db_session):
    _employee(db_session, "Priya", "DESKTOP-PRIYA")

    assert client.get("/v1/admin/overview").status_code == 401
    assert client.get("/v1/admin/overview", headers=_auth(client, "DESKTOP-PRIYA")).status_code == 403


def test_admin_overview_counts_statuses_and_lists_distracting_sites(client, db_session):
    _employee(db_session, "Admin", "DESKTOP-ADMIN", role="admin")
    now = time.time()
    working = _employee(db_session, "Aditi", "DESKTOP-ADITI")
    _active_minutes(db_session, _device(db_session, working), now - 600, 10)
    watching = _employee(db_session, "Farhan", "DESKTOP-FARHAN")
    farhan_device = _device(db_session, watching)
    _active_minutes(db_session, farhan_device, now - 600, 10, app="chrome.exe",
                    title="Top 10 IPL finishes - YouTube - Google Chrome")
    _device(db_session, _employee(db_session, "Meera", "DESKTOP-MEERA"), last_seen=now - 3 * 3600)
    db_session.add(Message(message_id=str(uuid.uuid4()), device_id=farhan_device.device_id, kind="distraction",
                           text="You've been on Top 10 IPL finishes for 10 minutes.", label="Top 10 IPL finishes",
                           created_at=now - 60))
    db_session.commit()

    body = client.get("/v1/admin/overview", headers=_auth(client, "DESKTOP-ADMIN")).json()

    # Admin has no device -> offline; Meera stopped syncing 3h ago -> offline.
    assert body["kpis"] == {"total": 4, "active": 1, "distraction": 1, "idle": 0, "offline": 2}
    by_name = {e["name"]: e for e in body["employees"]}
    assert by_name["Farhan"]["status"]["on_screen"]["title"] == "Top 10 IPL finishes - YouTube"
    assert by_name["Aditi"]["status"]["status"] == "active"
    (site,) = body["distracting_sites"]
    assert site["name"] == "YouTube" and site["rows"][0]["employee_name"] == "Farhan"
    assert body["messages"][0]["employee_name"] == "Farhan"
    assert len(body["trend"]) == 24 and sum(p["active_secs"] for p in body["trend"]) > 1000
    # Buckets start on whole local hours (not UTC ones -- IST is UTC+5:30).
    assert all(datetime.fromtimestamp(p["hour_start"]).minute == 0 for p in body["trend"])


def test_admin_can_hide_window_titles(client, db_session, monkeypatch):
    monkeypatch.setenv("ADMIN_SHOW_WINDOW_TITLES", "false")
    _employee(db_session, "Admin", "DESKTOP-ADMIN", role="admin")
    farhan = _employee(db_session, "Farhan", "DESKTOP-FARHAN")
    device = _device(db_session, farhan)
    _active_minutes(db_session, device, time.time() - 600, 10, app="chrome.exe",
                    title="Top 10 IPL finishes - YouTube - Google Chrome")
    db_session.add(Message(message_id=str(uuid.uuid4()), device_id=device.device_id, kind="distraction",
                           text="You've been on Top 10 IPL finishes for 10 minutes.", label="Top 10 IPL finishes"))
    db_session.commit()
    headers = _auth(client, "DESKTOP-ADMIN")

    overview = client.get("/v1/admin/overview", headers=headers).json()
    detail = client.get(f"/v1/admin/employees/{farhan.employee_id}", headers=headers).json()

    assert overview["show_titles"] is False
    row = [e for e in overview["employees"] if e["name"] == "Farhan"][0]
    assert row["status"]["on_screen"]["title"] is None and row["status"]["on_screen"]["app"] == "Chrome"
    assert overview["distracting_sites"][0]["rows"][0]["title"] is None
    assert "IPL" not in str(overview["messages"]) and "IPL" not in str(detail)


def test_admin_employee_detail(client, db_session):
    _employee(db_session, "Admin", "DESKTOP-ADMIN", role="admin")
    aditi = _employee(db_session, "Aditi", "DESKTOP-ADITI")
    _active_minutes(db_session, _device(db_session, aditi), time.time() - 600, 10, title="orchestrator.py - x")
    headers = _auth(client, "DESKTOP-ADMIN")

    body = client.get(f"/v1/admin/employees/{aditi.employee_id}", headers=headers).json()

    assert body["name"] == "Aditi"
    assert body["windows"][0]["title"] == "orchestrator.py - x"
    assert body["segments"][0]["state"] == "active"
    assert client.get("/v1/admin/employees/nope", headers=headers).status_code == 404


# ---------------------------------------------------------------- dev database upgrade


def test_add_missing_sqlite_columns_upgrades_an_old_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    old = MetaData()
    Table("employees", old, Column("employee_id", String, primary_key=True), Column("name", String))
    old.create_all(engine)

    new = MetaData()
    Table(
        "employees",
        new,
        Column("employee_id", String, primary_key=True),
        Column("name", String),
        Column("role", String, server_default="employee", nullable=False),
        Column("email", String),
    )

    added = add_missing_sqlite_columns(engine, new)

    assert sorted(added) == ["employees.email", "employees.role"]
    assert {c["name"] for c in inspect(engine).get_columns("employees")} == {"employee_id", "name", "role", "email"}
    assert add_missing_sqlite_columns(engine, new) == []
    engine.dispose()
