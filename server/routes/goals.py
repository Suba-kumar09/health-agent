from __future__ import annotations

import html
import time

from fastapi import APIRouter, Depends, Form
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from server.auth import resolve_employee_by_system_name
from server.db import get_session
from server.models import Goal

router = APIRouter()

_FORM_PAGE = """<!doctype html>
<title>Set today's goal</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 420px; margin: 3rem auto; }}
  label {{ display: block; margin-top: 1rem; font-weight: 600; }}
  input {{ width: 100%; padding: 0.5rem; margin-top: 0.25rem; box-sizing: border-box; }}
  button {{ margin-top: 1.5rem; padding: 0.6rem 1.2rem; }}
  .msg {{ margin-top: 1rem; padding: 0.75rem; border-radius: 4px; }}
  .ok {{ background: #e6f4ea; color: #1e7e34; }}
  .err {{ background: #fdecea; color: #b3261e; }}
</style>
<h1>Set today's goal</h1>
{message}
<form method="post" action="/goal">
  <label for="system_name">System name (this computer's name)</label>
  <input id="system_name" name="system_name" required>

  <label for="text">Goal</label>
  <input id="text" name="text" placeholder="e.g. Finish the quarterly report" required>

  <label for="hours">Hours to complete</label>
  <input id="hours" name="hours" type="number" step="0.5" min="0.5" required>

  <button type="submit">Set goal</button>
</form>
"""


@router.get("/goal", response_class=HTMLResponse)
def goal_form() -> str:
    return _FORM_PAGE.format(message="")


@router.post("/goal", response_class=HTMLResponse)
def submit_goal(
    system_name: str = Form(...),
    text: str = Form(...),
    hours: float = Form(...),
    session: Session = Depends(get_session),
) -> str:
    employee = resolve_employee_by_system_name(session, system_name)
    if employee is None:
        safe_system_name = html.escape(system_name)
        message = f'<p class="msg err">System \'{safe_system_name}\' is not a registered employee machine.</p>'
        return _FORM_PAGE.format(message=message)

    now = time.time()
    goal = Goal(employee_id=employee.employee_id, text=text, deadline_at=now + hours * 3600, created_at=now)
    session.add(goal)
    session.commit()

    safe_name = html.escape(employee.name)
    safe_text = html.escape(text)
    message = f'<p class="msg ok">Goal set for {safe_name}: "{safe_text}" (due in {hours:g}h).</p>'
    return _FORM_PAGE.format(message=message)
