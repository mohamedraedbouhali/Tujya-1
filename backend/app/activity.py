"""The activity log that administrators read (GET /api/admin/activity, decision D82).

Each event says who did what and when, from which address and browser, with a few counts.
It never holds a photo, a pill or medicine name, or the text of a question: those are health
data and stay with the user.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import delete
from sqlalchemy.orm import Session, sessionmaker

from app.db import utc_now
from app.models import Action, ActivityEvent

log = logging.getLogger("synergyrx.api")


def client_ip(request: Request) -> str | None:
    """The browser's address.

    Behind nginx (docker compose) it is the last X-Forwarded-For entry, the one nginx added
    itself; anything before it was written by the browser and is not trusted. The Vite dev
    proxy sends no such header, so the address is the direct client's.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()[:45] or None
    return request.client.host if request.client else None


def add_event(
    db: Session,
    user_id: int,
    action: Action,
    request: Request | None = None,
    *,
    target_id: int | None = None,
    **details: Any,
) -> None:
    """Add an event to `db`; the caller's commit saves it together with what it records."""
    agent = request.headers.get("user-agent") if request is not None else None
    db.add(
        ActivityEvent(
            user_id=user_id,
            action=action.value,
            target_id=target_id,
            details=details,
            ip=client_ip(request) if request is not None else None,
            user_agent=agent[:300] if agent else None,
        )
    )


def log_event(request: Request, user_id: int, action: Action, **details: Any) -> None:
    """Record an event in its own transaction, for routes that do not write accounts.

    Blocking: call it through run_in_threadpool from async routes. A failure is logged and
    swallowed, so the activity log can never break a scan or an answer.
    """
    factory: sessionmaker[Session] = request.app.state.session_factory
    try:
        with factory() as db:
            add_event(db, user_id, action, request, **details)
            db.commit()
    except Exception:
        log.exception("could not record the activity event %s", action.value)


def prune_activity(db: Session, days: int) -> int:
    """Delete the events older than `days` days (0 keeps everything). Returns how many."""
    if days <= 0:
        return 0
    cutoff = utc_now() - timedelta(days=days)
    result = db.execute(delete(ActivityEvent).where(ActivityEvent.created_at < cutoff))
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)
