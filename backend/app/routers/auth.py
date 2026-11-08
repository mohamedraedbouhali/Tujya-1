"""Sign up, sign in, sign out and the signed-in user's own account."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import delete, select

from app.accounts import (
    commit_or_conflict,
    create_user,
    end_session_cookie,
    ensure_email_free,
    get_user_by_email,
    revoke_sessions,
    start_session,
)
from app.activity import add_event
from app.db import utc_now
from app.deps import CurrentSession, CurrentUser, DbSession, SettingsDep
from app.images import (
    PHOTO_MAX_BYTES,
    SIGNATURE_MAX_BYTES,
    InvalidImage,
    make_photo,
    make_signature,
)
from app.models import Action, AuthSession, User
from app.schemas import LoginIn, PasswordChange, ProfileUpdate, SignupIn, UserOut
from app.security import hash_password, hash_token, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
ImageFile = Annotated[UploadFile, File(description="JPEG, PNG or WebP image")]
IMAGE_ERRORS: dict[int | str, dict[str, str]] = {
    413: {"description": "Image larger than the upload limit"},
    415: {"description": "Not a JPEG, PNG or WebP image, or one that cannot be used"},
}


def _process_upload(upload: UploadFile, max_bytes: int, process: Callable[[bytes], bytes]) -> bytes:
    if upload.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Send a JPEG, PNG or WebP image."
        )
    data = upload.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"The image is larger than {max_bytes // (1024 * 1024)} MB.",
        )
    try:
        return process(data)
    except InvalidImage as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc


@router.post("/signup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def sign_up(
    payload: SignupIn, request: Request, response: Response, db: DbSession, settings: SettingsDep
) -> User:
    """Create a regular account and sign it in. Administrators are only made by administrators."""
    ensure_email_free(db, payload.email)
    user = create_user(
        db, email=payload.email, full_name=payload.full_name, password=payload.password
    )
    start_session(db, user, response, settings)
    add_event(db, user.id, Action.SIGN_UP, request)
    commit_or_conflict(db)
    return user


@router.post("/login", response_model=UserOut)
def sign_in(
    payload: LoginIn, request: Request, response: Response, db: DbSession, settings: SettingsDep
) -> User:
    user = get_user_by_email(db, payload.email)
    # Always verify, even for an unknown email, and answer both failures the same way.
    if not verify_password(payload.password, user.password_hash if user else None) or not user:
        if user is not None:  # a wrong password for a real account goes into its activity
            add_event(db, user.id, Action.SIGN_IN_FAILED, request)
            db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if not user.is_active:
        add_event(db, user.id, Action.SIGN_IN_BLOCKED, request)
        db.commit()
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This account has been deactivated. Contact an administrator.",
        )
    start_session(db, user, response, settings)
    add_event(db, user.id, Action.SIGN_IN, request)
    db.commit()
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def sign_out(request: Request, response: Response, db: DbSession, settings: SettingsDep) -> None:
    """Always succeeds, so that an expired session can still be cleared from the browser."""
    token = request.cookies.get(settings.session_cookie)
    if token:
        hashed = hash_token(token)
        owner = db.scalar(select(AuthSession.user_id).where(AuthSession.token_hash == hashed))
        if owner is not None:
            add_event(db, owner, Action.SIGN_OUT, request)
        db.execute(delete(AuthSession).where(AuthSession.token_hash == hashed))
        db.commit()
    end_session_cookie(response, settings)


@router.get("/me", response_model=UserOut)
def read_me(user: CurrentUser) -> User:
    return user


@router.patch("/me", response_model=UserOut)
def update_me(payload: ProfileUpdate, request: Request, user: CurrentUser, db: DbSession) -> User:
    """Change the name, email or phone number; only the fields sent change."""
    changed: list[str] = []
    if payload.email is not None and payload.email != user.email:
        # A browser left signed in must not be enough to take the account over.
        if not payload.current_password:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Enter your current password to change your email"
            )
        if not verify_password(payload.current_password, user.password_hash):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "The current password is incorrect")
        ensure_email_free(db, payload.email, except_user_id=user.id)
        user.email = payload.email
        changed.append("email")
    if payload.full_name is not None and payload.full_name != user.full_name:
        user.full_name = payload.full_name
        changed.append("name")
    if payload.phone is not None and (payload.phone or None) != user.phone:
        user.phone = payload.phone or None
        changed.append("phone")
    if changed:
        add_event(db, user.id, Action.PROFILE_UPDATE, request, fields=changed)
    commit_or_conflict(db)
    return user


@router.put("/me/photo", response_model=UserOut, responses=IMAGE_ERRORS)
def upload_photo(image: ImageFile, request: Request, user: CurrentUser, db: DbSession) -> User:
    """Set the profile photo: the centre square of the image, stored as a 256 px JPEG."""
    user.photo = _process_upload(image, PHOTO_MAX_BYTES, make_photo)
    user.photo_updated_at = utc_now()
    add_event(db, user.id, Action.PHOTO_UPDATE, request)
    db.commit()
    return user


@router.delete("/me/photo", response_model=UserOut)
def delete_photo(request: Request, user: CurrentUser, db: DbSession) -> User:
    if user.photo_updated_at is not None:
        add_event(db, user.id, Action.PHOTO_DELETE, request)
    user.photo = None
    user.photo_updated_at = None
    db.commit()
    return user


@router.put("/me/signature", response_model=UserOut, responses=IMAGE_ERRORS)
def upload_signature(image: ImageFile, request: Request, user: CurrentUser, db: DbSession) -> User:
    """Set the signature, drawn in the app or uploaded; stored as a PNG."""
    user.signature = _process_upload(image, SIGNATURE_MAX_BYTES, make_signature)
    user.signature_updated_at = utc_now()
    add_event(db, user.id, Action.SIGNATURE_UPDATE, request)
    db.commit()
    return user


@router.delete("/me/signature", response_model=UserOut)
def delete_signature(request: Request, user: CurrentUser, db: DbSession) -> User:
    if user.signature_updated_at is not None:
        add_event(db, user.id, Action.SIGNATURE_DELETE, request)
    user.signature = None
    user.signature_updated_at = None
    db.commit()
    return user


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_my_password(
    payload: PasswordChange, request: Request, session: CurrentSession, db: DbSession
) -> None:
    """Change the password and sign out every other browser of this account."""
    user = session.user
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    revoke_sessions(db, user.id, keep=session)
    add_event(db, user.id, Action.PASSWORD_CHANGE, request)
    db.commit()
