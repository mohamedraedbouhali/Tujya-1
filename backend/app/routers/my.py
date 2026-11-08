"""The user's own data (decision D83): "My medicines", kept between visits, and saved reports
with their share links. Only the owner reads them; administrators never do.

POST /api/shared opens a shared report without signing in, from the token of its link.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.activity import add_event
from app.db import utc_now
from app.deps import CurrentUser, DbSession, PharmaSession
from app.medicines import PharmaUnavailable, pill_infos, sources
from app.models import Action, Report, SavedPill, User
from app.reports import (
    body_fields,
    new_share_token,
    seal_is_valid,
    share_state,
    snapshot,
    summary_fields,
)
from app.routers.medicines import interactions_report
from app.routers.scan import pharma_unavailable
from app.schemas import (
    ChatExcerpt,
    ReportIn,
    ReportOut,
    ReportPage,
    ReportPill,
    ReportSummary,
    SavedPillIn,
    SavedPillList,
    SavedPillOut,
    ShareCreated,
    SharedIn,
    SharedReport,
    ShareIn,
    SourceOut,
)
from app.security import hash_token

router = APIRouter(prefix="/api/my", tags=["my data"])
public_router = APIRouter(prefix="/api", tags=["my data"])

# The interaction check takes 10 medicines at most, so the list holds as many.
MAX_SAVED_PILLS = 10
MAX_REPORTS = 100


# --- my medicines ---------------------------------------------------------------------------


def _saved_list(db: Session, pharma: Session, user: User) -> SavedPillList:
    rows = db.scalars(
        select(SavedPill)
        .where(SavedPill.user_id == user.id)
        .order_by(SavedPill.added_at, SavedPill.id)
    ).all()
    try:
        infos = pill_infos(pharma, [row.class_id for row in rows])
        cited = sources(pharma, ["c3pi", "rxnav"])
    except PharmaUnavailable as exc:
        raise pharma_unavailable() from exc
    items = []
    for row in rows:
        info = infos.get(row.class_id)  # None if the medicine tables were rebuilt without it
        items.append(
            SavedPillOut(
                class_id=row.class_id,
                name=info.name if info else f"class {row.class_id}",
                generic_name=info.generic_name if info else "",
                active_ingredients=info.ingredients if info else [],
                probability=row.probability,
                added_at=row.added_at,
            )
        )
    return SavedPillList(items=items, sources=[SourceOut.model_validate(s) for s in cited])


@router.get("/medicines", response_model=SavedPillList)
def list_medicines(db: DbSession, pharma: PharmaSession, user: CurrentUser) -> SavedPillList:
    """The pills the user confirmed on the Scanner page, kept between visits."""
    return _saved_list(db, pharma, user)


@router.post("/medicines", response_model=SavedPillList)
def add_medicine(
    payload: SavedPillIn, db: DbSession, pharma: PharmaSession, user: CurrentUser
) -> SavedPillList:
    """Add a pill class to the list (once: adding it again only updates its probability)."""
    try:
        known = payload.class_id in pill_infos(pharma, [payload.class_id])
    except PharmaUnavailable as exc:
        raise pharma_unavailable() from exc
    if not known:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No pill has this class_id.")
    row = db.scalar(
        select(SavedPill).where(
            SavedPill.user_id == user.id, SavedPill.class_id == payload.class_id
        )
    )
    if row is None:
        count = db.scalar(select(func.count()).where(SavedPill.user_id == user.id)) or 0
        if count >= MAX_SAVED_PILLS:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Your list already holds {MAX_SAVED_PILLS} medicines. Remove one first.",
            )
        db.add(
            SavedPill(user_id=user.id, class_id=payload.class_id, probability=payload.probability)
        )
    elif payload.probability is not None:
        row.probability = payload.probability
    try:
        db.commit()
    except IntegrityError:  # the same pill added twice at once: it is in the list either way
        db.rollback()
    return _saved_list(db, pharma, user)


@router.delete("/medicines/{class_id}", response_model=SavedPillList)
def remove_medicine(
    class_id: int, db: DbSession, pharma: PharmaSession, user: CurrentUser
) -> SavedPillList:
    db.execute(
        delete(SavedPill).where(SavedPill.user_id == user.id, SavedPill.class_id == class_id)
    )
    db.commit()
    return _saved_list(db, pharma, user)


@router.delete("/medicines", status_code=status.HTTP_204_NO_CONTENT)
def clear_medicines(db: DbSession, user: CurrentUser) -> None:
    db.execute(delete(SavedPill).where(SavedPill.user_id == user.id))
    db.commit()


# --- reports --------------------------------------------------------------------------------


def _own_report(db: Session, user: User, report_id: int) -> Report:
    report = db.get(Report, report_id)
    # The same 404 for "not yours" and "not there": ids cannot be probed.
    if report is None or report.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    return report


def _report_out(report: Report) -> ReportOut:
    return ReportOut(**body_fields(report), share=share_state(report, utc_now()))


@router.get("/reports", response_model=ReportPage)
def list_reports(
    db: DbSession,
    user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
) -> ReportPage:
    """The user's saved reports, newest first: their history of checks."""
    total = db.scalar(select(func.count()).where(Report.user_id == user.id)) or 0
    rows = db.scalars(
        select(Report)
        .where(Report.user_id == user.id)
        .order_by(Report.created_at.desc(), Report.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    now = utc_now()
    return ReportPage(
        items=[ReportSummary(**summary_fields(r), share=share_state(r, now)) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/reports",
    response_model=ReportOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"description": "Too many reports kept"},
        422: {"description": "A chat answer whose seal does not match"},
    },
)
def create_report(
    payload: ReportIn,
    request: Request,
    db: DbSession,
    pharma: PharmaSession,
    user: CurrentUser,
) -> ReportOut:
    """Save a report: the interactions between the pills are checked again now, and kept with
    the chat answers chosen, as they are today. Each answer must come with its seal."""
    key: bytes = request.app.state.answer_key
    chat = []
    for item in payload.chat:
        excerpt = ChatExcerpt(question=item.question, answer=item.answer, citations=item.citations)
        if not seal_is_valid(key, excerpt, item.signature):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "A chat answer could not be verified: it was changed, or asked before the "
                "server restarted. Ask the question again, then save the report.",
            )
        chat.append(excerpt)

    count = db.scalar(select(func.count()).where(Report.user_id == user.id)) or 0
    if count >= MAX_REPORTS:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"You already keep {MAX_REPORTS} reports. Delete old ones first.",
        )

    pill_ids = list(dict.fromkeys(payload.pills))  # each class once, in the order given
    try:
        infos = pill_infos(pharma, pill_ids) if pill_ids else {}
        unknown = [str(i) for i in pill_ids if i not in infos]
        if unknown:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"No pill has this class_id: {', '.join(unknown)}."
            )
        interactions = interactions_report(pharma, pill_ids, []) if len(pill_ids) >= 2 else None
    except PharmaUnavailable as exc:
        raise pharma_unavailable() from exc
    pills = [
        ReportPill(
            class_id=i,
            name=infos[i].name,
            generic_name=infos[i].generic_name,
            active_ingredients=infos[i].ingredients,
        )
        for i in pill_ids
    ]

    report = Report(user_id=user.id, title=payload.title, data=snapshot(pills, interactions, chat))
    db.add(report)
    # How many medicines and answers, never which ones (D82).
    add_event(db, user.id, Action.REPORT_CREATE, request, items=len(pills), answers=len(chat))
    db.commit()
    return _report_out(report)


@router.get("/reports/{report_id}", response_model=ReportOut)
def read_report(report_id: int, db: DbSession, user: CurrentUser) -> ReportOut:
    return _report_out(_own_report(db, user, report_id))


@router.delete("/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(report_id: int, request: Request, db: DbSession, user: CurrentUser) -> None:
    """Delete a report; its share link stops working with it."""
    db.delete(_own_report(db, user, report_id))
    add_event(db, user.id, Action.REPORT_DELETE, request)
    db.commit()


@router.post("/reports/{report_id}/share", response_model=ShareCreated)
def share_report(
    report_id: int, payload: ShareIn, request: Request, db: DbSession, user: CurrentUser
) -> ShareCreated:
    """Make a read-only link for a pharmacist or doctor, valid `days` days. A new link
    replaces the previous one. The token is shown this once; only its hash is kept."""
    report = _own_report(db, user, report_id)
    token, token_hash = new_share_token()
    report.share_token_hash = token_hash
    report.share_expires_at = utc_now() + timedelta(days=payload.days)
    report.share_views = 0
    add_event(db, user.id, Action.REPORT_SHARE, request, days=payload.days)
    db.commit()
    return ShareCreated(token=token, expires_at=report.share_expires_at)


@router.delete("/reports/{report_id}/share", status_code=status.HTTP_204_NO_CONTENT)
def stop_sharing(report_id: int, request: Request, db: DbSession, user: CurrentUser) -> None:
    report = _own_report(db, user, report_id)
    if report.share_token_hash is not None or report.share_expires_at is not None:
        report.share_token_hash = None
        report.share_expires_at = None
        add_event(db, user.id, Action.REPORT_UNSHARE, request)
        db.commit()


@public_router.post(
    "/shared",
    response_model=SharedReport,
    responses={404: {"description": "Wrong, expired or stopped link"}},
)
def open_shared_report(payload: SharedIn, response: Response, db: DbSession) -> SharedReport:
    """A shared report, read only, without signing in. The token travels in the body (and
    after the # of the page address), so no server or proxy log ever holds it."""
    report = db.scalar(select(Report).where(Report.share_token_hash == hash_token(payload.token)))
    if (
        report is None
        or report.share_expires_at is None
        or report.share_expires_at <= utc_now()
        or not report.user.is_active
    ):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "This link does not work: it is wrong, has expired, or its owner stopped sharing.",
        )
    db.execute(
        update(Report).where(Report.id == report.id).values(share_views=Report.share_views + 1)
    )
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex"
    return SharedReport(**body_fields(report), expires_at=report.share_expires_at)
