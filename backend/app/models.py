"""Database tables: accounts, their sign-in sessions, their activity, and what each user keeps
(saved medicines and reports, D83)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UTCDateTime, utc_now


class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"


def _image_url(user_id: int, kind: str, updated_at: datetime | None) -> str | None:
    """Address of a stored image; it changes with every upload, so browsers may cache it."""
    if updated_at is None:
        return None
    return f"/api/users/{user_id}/{kind}?v={int(updated_at.timestamp() * 1000)}"


class User(Base):
    __tablename__ = "users"
    # Never hand the id of a deleted account to a new one: an administrator's open
    # "edit user 7" dialog must not end up editing somebody else.
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)  # lower case
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default=Role.USER.value)  # a Role value
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    phone: Mapped[str | None] = mapped_column(String(32), default=None)
    # Profile photo (JPEG) and signature (PNG), both re-encoded by the server (app/images.py).
    # Deferred: only the image routes read them, never a normal account query.
    photo: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True, default=None)
    photo_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    signature: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True, default=None)
    signature_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)

    sessions: Mapped[list[AuthSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    # Deleting an account deletes what it did; what administrators did to it stays (with
    # the name and email copied into the event), so a deletion is itself on record.
    activity: Mapped[list[ActivityEvent]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    # Health data the user chose to keep: deleted with the account, never shown to admins.
    saved_pills: Mapped[list[SavedPill]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
    reports: Mapped[list[Report]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def photo_url(self) -> str | None:
        return _image_url(self.id, "photo", self.photo_updated_at)

    @property
    def signature_url(self) -> str | None:
        return _image_url(self.id, "signature", self.signature_updated_at)


class AuthSession(Base):
    """One signed-in browser. Only the SHA-256 of the cookie value is stored."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)

    user: Mapped[User] = relationship(back_populates="sessions")


class Action(StrEnum):
    """What an activity event records. The frontend has a label for each (locales/*.ts)."""

    SIGN_UP = "sign_up"
    SIGN_IN = "sign_in"
    SIGN_IN_FAILED = "sign_in_failed"  # wrong password for an existing account
    SIGN_IN_BLOCKED = "sign_in_blocked"  # right password, deactivated account
    SIGN_OUT = "sign_out"
    SCAN = "scan"
    INTERACTIONS = "interactions"
    CHAT = "chat"
    TOXICITY = "toxicity"
    PROFILE_UPDATE = "profile_update"
    PHOTO_UPDATE = "photo_update"
    PHOTO_DELETE = "photo_delete"
    SIGNATURE_UPDATE = "signature_update"
    SIGNATURE_DELETE = "signature_delete"
    PASSWORD_CHANGE = "password_change"  # noqa: S105  an action name, not a password
    # Done by an administrator to another account (target_id, name and email in details).
    USER_CREATE = "user_create"
    USER_UPDATE = "user_update"
    PASSWORD_RESET = "password_reset"  # noqa: S105  an action name, not a password
    USER_DELETE = "user_delete"
    # Reports (D83): how many medicines, or for how many days a link is shared; never which.
    REPORT_CREATE = "report_create"
    REPORT_SHARE = "report_share"
    REPORT_UNSHARE = "report_unshare"
    REPORT_DELETE = "report_delete"
    # An administrator downloaded a table as CSV (details: which table, how many rows).
    DATA_EXPORT = "data_export"


class ActivityEvent(Base):
    """One thing an account did, for the administrators' activity log.

    Only what happened and when, with counts: never a photo, a pill or medicine name, or the
    text of a question (health data stays with the user, D82).
    """

    __tablename__ = "activity"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, index=True)
    # Who did it. Deleting the account deletes its events (ON DELETE CASCADE).
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)  # an Action value
    # The account an administrator acted on. No foreign key: the event outlives a deletion.
    target_id: Mapped[int | None] = mapped_column(default=None, index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(45), default=None)
    user_agent: Mapped[str | None] = mapped_column(String(300), default=None)

    user: Mapped[User] = relationship(back_populates="activity")


class SavedPill(Base):
    """A pill in the user's "My medicines" list, kept between visits (Scanner page, D83).

    Only the class_id is stored: names and ingredients are read from the medicine tables, so
    they always match the current data. Only its owner can read it.
    """

    __tablename__ = "saved_pills"
    __table_args__ = (UniqueConstraint("user_id", "class_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    class_id: Mapped[int]
    # The model's probability when confirmed from a scan; null when picked by search.
    probability: Mapped[float | None] = mapped_column(default=None)
    added_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now)

    user: Mapped[User] = relationship(back_populates="saved_pills")


class Report(Base):
    """A saved interaction report: what the check found on that day, kept as it was (D83).

    `data` is a snapshot (pills, interaction result, chosen chat answers), so the report does
    not change when the medicine tables do. A share link is stored as the SHA-256 of its
    token, like a session: the token itself is shown once, to the owner.
    """

    __tablename__ = "reports"
    # Never reuse the id of a deleted report: an old browser tab must not open another one.
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utc_now, index=True)
    title: Mapped[str] = mapped_column(String(120), default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    share_token_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, default=None
    )
    share_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    share_views: Mapped[int] = mapped_column(default=0)

    user: Mapped[User] = relationship(back_populates="reports")
