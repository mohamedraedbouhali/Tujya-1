"""Profile photos and signatures. Everyone sees their own; administrators see everyone's."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.deps import CurrentUser, DbSession
from app.models import Role, User

router = APIRouter(prefix="/api/users", tags=["users"])


def _image(
    db: Session,
    viewer: User,
    user_id: int,
    column: InstrumentedAttribute[bytes | None],
    media_type: str,
) -> Response:
    # The same 404 for "not yours" and "not there": ids cannot be probed.
    not_found = HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    if viewer.id != user_id and viewer.role != Role.ADMIN:
        raise not_found
    data = db.scalar(select(column).where(User.id == user_id))
    if data is None:
        raise not_found
    return Response(data, media_type=media_type, headers={"X-Content-Type-Options": "nosniff"})


@router.get(
    "/{user_id}/photo",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}, 404: {"description": "No photo"}},
)
def read_photo(user_id: int, viewer: CurrentUser, db: DbSession) -> Response:
    response = _image(db, viewer, user_id, User.photo, "image/jpeg")
    # Shown on every page; its address changes with each upload, so it can be kept.
    response.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    return response


@router.get(
    "/{user_id}/signature",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}, 404: {"description": "No signature"}},
)
def read_signature(user_id: int, viewer: CurrentUser, db: DbSession) -> Response:
    response = _image(db, viewer, user_id, User.signature, "image/png")
    # Never left behind in the cache of a shared computer.
    response.headers["Cache-Control"] = "no-store"
    return response
