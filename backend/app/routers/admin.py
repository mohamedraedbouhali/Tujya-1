"""Administration: every route here requires a signed-in administrator."""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session, contains_eager

from app.accounts import commit_or_conflict, create_user, ensure_email_free, revoke_sessions
from app.activity import add_event
from app.db import utc_now
from app.deps import AdminUser, CurrentSession, DbSession, require_admin
from app.models import Action, ActivityEvent, AuthSession, Report, Role, User
from app.schemas import (
    ActivityOut,
    ActivityPage,
    AdminPasswordReset,
    AdminStats,
    AdminUserCreate,
    AdminUserUpdate,
    UsageDay,
    UsageReport,
    UserOut,
    UserPage,
)
from app.security import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router.get("/stats", response_model=AdminStats)
def read_stats(db: DbSession) -> AdminStats:
    now = utc_now()

    def count(*conditions: object) -> int:
        return db.scalar(select(func.count()).select_from(User).where(*conditions)) or 0

    total = count()
    active = count(User.is_active)
    sessions = select(func.count()).select_from(AuthSession).where(AuthSession.expires_at > now)
    return AdminStats(
        users_total=total,
        users_active=active,
        users_inactive=total - active,
        admins=count(User.role == Role.ADMIN, User.is_active),
        signups_last_7_days=count(User.created_at >= now - timedelta(days=7)),
        active_sessions=db.scalar(sessions) or 0,
    )


@router.get("/users", response_model=UserPage)
def list_users(
    db: DbSession,
    q: Annotated[str, Query(max_length=100, description="Part of a name or an email")] = "",
    role: Role | None = None,
    state: Annotated[Literal["active", "inactive"] | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> UserPage:
    conditions = []
    if q.strip():
        needle = q.strip()
        conditions.append(
            or_(
                User.email.icontains(needle, autoescape=True),
                User.full_name.icontains(needle, autoescape=True),
            )
        )
    if role is not None:
        conditions.append(User.role == role)
    if state is not None:
        conditions.append(User.is_active.is_(state == "active"))

    total = db.scalar(select(func.count()).select_from(User).where(*conditions)) or 0
    rows = db.scalars(
        select(User)
        .where(*conditions)
        .order_by(User.created_at.desc(), User.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return UserPage(
        items=[UserOut.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: AdminUserCreate, request: Request, admin: AdminUser, db: DbSession
) -> User:
    ensure_email_free(db, payload.email)
    user = create_user(
        db,
        email=payload.email,
        full_name=payload.full_name,
        password=payload.password,
        role=payload.role,
        is_active=payload.is_active,
    )
    add_event(
        db,
        admin.id,
        Action.USER_CREATE,
        request,
        target_id=user.id,
        name=user.full_name,
        email=user.email,
        role=user.role,
        active=user.is_active,
    )
    commit_or_conflict(db)
    return user


@router.get("/users/{user_id}", response_model=UserOut)
def read_account(user_id: int, db: DbSession) -> User:
    return _get_user(db, user_id)


@router.patch("/users/{user_id}", response_model=UserOut)
def update_account(
    user_id: int, payload: AdminUserUpdate, request: Request, admin: AdminUser, db: DbSession
) -> User:
    user = _get_user(db, user_id)
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)

    # An administrator cannot lock themselves out. Since only another administrator can
    # demote or deactivate one, at least one active administrator always remains.
    if user.id == admin.id:
        if changes.get("role", Role.ADMIN) != Role.ADMIN:
            raise HTTPException(status.HTTP_409_CONFLICT, "You cannot change your own role")
        if changes.get("is_active") is False:
            raise HTTPException(status.HTTP_409_CONFLICT, "You cannot deactivate your own account")

    changed: dict[str, object] = {}  # only what really changes goes into the activity log
    if "email" in changes and changes["email"] != user.email:
        ensure_email_free(db, changes["email"], except_user_id=user.id)
        user.email = changes["email"]
        changed["email"] = True
    if "full_name" in changes and changes["full_name"] != user.full_name:
        user.full_name = changes["full_name"]
        changed["name"] = True
    if "role" in changes and changes["role"].value != user.role:
        user.role = changes["role"].value
        changed["role"] = user.role
    if "is_active" in changes and changes["is_active"] != user.is_active:
        user.is_active = changes["is_active"]
        changed["active"] = user.is_active
        if not user.is_active:
            revoke_sessions(db, user.id)
    if changed:
        add_event(
            db,
            admin.id,
            Action.USER_UPDATE,
            request,
            target_id=user.id,
            name=user.full_name,
            email=user.email,
            changes=changed,
        )
    commit_or_conflict(db)
    return user


@router.post("/users/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    user_id: int,
    payload: AdminPasswordReset,
    request: Request,
    session: CurrentSession,
    db: DbSession,
) -> None:
    """Set a new password and sign the user out everywhere.

    Passwords are stored as Argon2 hashes: they can be replaced, never read back.
    """
    user = _get_user(db, user_id)
    user.password_hash = hash_password(payload.new_password)
    # An administrator resetting their own password stays signed in on this browser.
    revoke_sessions(db, user.id, keep=session if session.user_id == user.id else None)
    add_event(
        db,
        session.user_id,
        Action.PASSWORD_RESET,
        request,
        target_id=user.id,
        name=user.full_name,
        email=user.email,
    )
    db.commit()


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(user_id: int, request: Request, admin: AdminUser, db: DbSession) -> None:
    """Delete the account, its sessions and its own activity. The deletion itself is logged
    under the administrator, with the name and email the account had."""
    user = _get_user(db, user_id)
    if user.id == admin.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot delete your own account")
    add_event(
        db,
        admin.id,
        Action.USER_DELETE,
        request,
        target_id=user.id,
        name=user.full_name,
        email=user.email,
    )
    db.delete(user)
    db.commit()


UserIdFilter = Annotated[
    int | None,
    Query(description="Events of this account, and those of administrators acting on it"),
]
ActionFilter = Annotated[list[Action] | None, Query(description="One or more actions")]
NameFilter = Annotated[str, Query(max_length=100, description="Part of a name or an email")]
DaysFilter = Annotated[int | None, Query(ge=1, le=3650, description="Only the last N days")]


def _activity_conditions(
    user_id: int | None, q: str, days: int | None
) -> list[ColumnElement[bool]]:
    """Filters shared by the activity list and its CSV export (the action filter apart)."""
    conditions: list[ColumnElement[bool]] = []
    if user_id is not None:
        conditions.append(or_(ActivityEvent.user_id == user_id, ActivityEvent.target_id == user_id))
    if q.strip():
        needle = q.strip()
        conditions.append(
            or_(
                User.email.icontains(needle, autoescape=True),
                User.full_name.icontains(needle, autoescape=True),
            )
        )
    if days is not None:
        conditions.append(ActivityEvent.created_at >= utc_now() - timedelta(days=days))
    return conditions


@router.get("/activity", response_model=ActivityPage)
def list_activity(
    db: DbSession,
    user_id: UserIdFilter = None,
    action: ActionFilter = None,
    q: NameFilter = "",
    days: DaysFilter = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> ActivityPage:
    """What accounts did, newest first: sign-ins, scans, checks, questions, account changes.

    Events hold counts only, never a medicine name or the text of a question.
    """
    conditions = _activity_conditions(user_id, q, days)

    # The numbers next to each filter ignore the action filter itself.
    per_action = db.execute(
        select(ActivityEvent.action, func.count())
        .join(ActivityEvent.user)
        .where(*conditions)
        .group_by(ActivityEvent.action)
    ).all()
    if action:
        conditions.append(ActivityEvent.action.in_([a.value for a in action]))

    total = (
        db.scalar(
            select(func.count())
            .select_from(ActivityEvent)
            .join(ActivityEvent.user)
            .where(*conditions)
        )
        or 0
    )
    rows = db.scalars(
        select(ActivityEvent)
        .join(ActivityEvent.user)
        .options(contains_eager(ActivityEvent.user))
        .where(*conditions)
        .order_by(ActivityEvent.created_at.desc(), ActivityEvent.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ActivityPage(
        items=[ActivityOut.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        counts={str(name): int(count) for name, count in per_action},
    )


# --- usage report and CSV exports (D83) -----------------------------------------------------

# Failed or refused sign-ins are recorded under the account, but nobody used the site.
NOT_ACTIVITY = {Action.SIGN_IN_FAILED.value, Action.SIGN_IN_BLOCKED.value}
EXPORT_MAX_ROWS = 50_000
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


@router.get("/usage", response_model=UsageReport)
def read_usage(
    db: DbSession,
    days: Annotated[int, Query(ge=1, le=366, description="Length of the period")] = 30,
    tz: Annotated[
        int,
        Query(ge=-840, le=840, description="Minutes to add to UTC to get local days (UTC+1: 60)"),
    ] = 0,
) -> UsageReport:
    """Events per day and per action, and active accounts, over the last `days` days.

    Counts only: like the activity log, it never says which medicine or question (D82).
    """
    now = utc_now()
    shift = timedelta(minutes=tz)
    first = (now + shift).date() - timedelta(days=days - 1)
    since = datetime.combine(first, time.min, tzinfo=UTC) - shift

    buckets: dict[Any, tuple[Counter[str], set[int]]] = {
        first + timedelta(days=n): (Counter(), set()) for n in range(days)
    }
    rows = db.execute(
        select(ActivityEvent.created_at, ActivityEvent.action, ActivityEvent.user_id).where(
            ActivityEvent.created_at >= since
        )
    ).all()
    for created_at, action, user_id in rows:
        bucket = buckets.get((created_at + shift).date())
        if bucket is None:
            continue
        bucket[0][action] += 1
        if action not in NOT_ACTIVITY:
            bucket[1].add(user_id)

    totals: Counter[str] = Counter()
    everyone: set[int] = set()
    out = []
    for day, (counts, users) in buckets.items():
        totals.update(counts)
        everyone |= users
        out.append(UsageDay(date=day.isoformat(), counts=dict(counts), active_users=len(users)))

    def count(table: Any, *conditions: Any) -> int:
        return db.scalar(select(func.count()).select_from(table).where(*conditions)) or 0

    return UsageReport(
        days=out,
        totals=dict(totals),
        active_users=len(everyone),
        new_accounts=count(User, User.created_at >= since),
        reports_saved=count(Report),
        shared_now=count(
            Report, Report.share_token_hash.is_not(None), Report.share_expires_at > now
        ),
    )


def _cell(value: object) -> object:
    """A spreadsheet runs a text cell that starts with = + - @ as a formula: neutralise it."""
    if isinstance(value, str) and value.startswith(FORMULA_START):
        return "'" + value
    return value


def _csv(name: str, header: list[str], rows: Iterable[Iterable[object]]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_cell("" if value is None else value) for value in row])
    filename = f"tujya-{name}-{utc_now():%Y-%m-%d}.csv"
    # The byte order mark makes Excel read accents and Cyrillic names correctly.
    return Response(
        "﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/export/users.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "Every account, as CSV"}},
)
def export_users(request: Request, admin: AdminUser, db: DbSession) -> Response:
    """Every account as a CSV file (no password hash, photo or signature). The download is
    recorded in the activity log."""
    users = db.scalars(select(User).order_by(User.id)).all()
    add_event(db, admin.id, Action.DATA_EXPORT, request, table="users", rows=len(users))
    db.commit()
    return _csv(
        "users",
        ["id", "email", "full_name", "role", "active", "phone", "created_at", "last_login_at"],
        (
            [
                u.id,
                u.email,
                u.full_name,
                u.role,
                u.is_active,
                u.phone,
                u.created_at.isoformat(),
                u.last_login_at.isoformat() if u.last_login_at else None,
            ]
            for u in users
        ),
    )


@router.get(
    "/export/activity.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}, "description": "Activity events, as CSV"}},
)
def export_activity(
    request: Request,
    admin: AdminUser,
    db: DbSession,
    user_id: UserIdFilter = None,
    action: ActionFilter = None,
    q: NameFilter = "",
    days: DaysFilter = None,
) -> Response:
    """The activity log with the same filters as GET /activity, newest first, as a CSV file
    (50,000 rows at most). Counts only, never a medicine or a question."""
    conditions = _activity_conditions(user_id, q, days)
    if action:
        conditions.append(ActivityEvent.action.in_([a.value for a in action]))
    events = db.scalars(
        select(ActivityEvent)
        .join(ActivityEvent.user)
        .options(contains_eager(ActivityEvent.user))
        .where(*conditions)
        .order_by(ActivityEvent.created_at.desc(), ActivityEvent.id.desc())
        .limit(EXPORT_MAX_ROWS)
    ).all()
    lines = [
        [
            e.id,
            e.created_at.isoformat(),
            e.user_id,
            e.user.email,
            e.user.full_name,
            e.action,
            e.target_id,
            json.dumps(e.details, ensure_ascii=False, sort_keys=True) if e.details else None,
            e.ip,
            e.user_agent,
        ]
        for e in events
    ]
    add_event(db, admin.id, Action.DATA_EXPORT, request, table="activity", rows=len(lines))
    db.commit()
    header = ["id", "created_at", "user_id", "email", "full_name", "action", "target_id"]
    return _csv("activity", [*header, "details", "ip", "user_agent"], lines)
