"""Saved reports, their share links, and the seal on chat answers (decision D83).

A report keeps a snapshot of an interaction check (and of chosen chat answers) as it was on
the day it was made. Chat answers come back from the browser, so each one must carry the
seal the server put on it (`ChatResult.signature`): a report, which can be shared, can
never hold an answer the agent did not give, such as an edited one that calls a combination
safe.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime
from typing import Any

from app.medicines import DISCLAIMER
from app.models import Report, User
from app.schemas import (
    ChatExcerpt,
    CitationRef,
    InteractionsResult,
    ReportPill,
    ShareState,
)
from app.security import hash_token

# --- the seal on chat answers ---------------------------------------------------------------


def new_signing_key(configured: str) -> bytes:
    """The configured key, or a random one for this run (answers sealed before a restart
    then need asking again)."""
    return configured.encode("utf-8") if configured else secrets.token_bytes(32)


def _canonical(question: str, answer: str, citations: list[CitationRef]) -> bytes:
    body = {"q": question, "a": answer, "c": [[c.n, c.title, c.url] for c in citations]}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def seal(key: bytes, question: str, answer: str, citations: list[CitationRef]) -> str:
    return hmac.new(key, _canonical(question, answer, citations), hashlib.sha256).hexdigest()


def seal_is_valid(key: bytes, excerpt: ChatExcerpt, signature: str) -> bool:
    expected = seal(key, excerpt.question, excerpt.answer, excerpt.citations)
    return hmac.compare_digest(expected, signature)


# --- share links ----------------------------------------------------------------------------


def new_share_token() -> tuple[str, str]:
    """A link token and the hash that is stored. 192 random bits: not guessable."""
    token = secrets.token_urlsafe(24)
    return token, hash_token(token)


def share_state(report: Report, now: datetime) -> ShareState | None:
    if report.share_expires_at is None:
        return None
    active = report.share_token_hash is not None and report.share_expires_at > now
    return ShareState(active=active, expires_at=report.share_expires_at, views=report.share_views)


# --- what a report says ---------------------------------------------------------------------


def snapshot(
    pills: list[ReportPill], interactions: InteractionsResult | None, chat: list[ChatExcerpt]
) -> dict[str, Any]:
    return {
        "pills": [p.model_dump() for p in pills],
        "interactions": interactions.model_dump(mode="json") if interactions else None,
        "chat": [c.model_dump() for c in chat],
    }


def _interactions(report: Report) -> InteractionsResult | None:
    data = report.data.get("interactions")
    return InteractionsResult.model_validate(data) if data else None


def signature_data_url(user: User) -> str | None:
    if user.signature is None:
        return None
    return "data:image/png;base64," + base64.b64encode(user.signature).decode("ascii")


def body_fields(report: Report) -> dict[str, Any]:
    """The fields of ReportBody, for the owner's view and the shared one."""
    interactions = _interactions(report)
    return {
        "id": report.id,
        "created_at": report.created_at,
        "title": report.title,
        "pills": [ReportPill.model_validate(p) for p in report.data.get("pills", [])],
        "interactions": interactions,
        "chat": [ChatExcerpt.model_validate(c) for c in report.data.get("chat", [])],
        "highest_severity": interactions.highest_severity if interactions else None,
        "author": report.user.full_name,
        "signature": signature_data_url(report.user),
        "disclaimer": DISCLAIMER,
    }


def summary_fields(report: Report) -> dict[str, Any]:
    interactions = _interactions(report)
    pairs = interactions.pairs if interactions else []
    return {
        "id": report.id,
        "created_at": report.created_at,
        "title": report.title,
        "pill_names": [p["name"] for p in report.data.get("pills", [])],
        "ingredients": sorted(
            {name for p in report.data.get("pills", []) for name in p["active_ingredients"]}
        ),
        "highest_severity": interactions.highest_severity if interactions else None,
        "pairs_with_interaction": sum(1 for pair in pairs if pair.interactions),
        "chat_answers": len(report.data.get("chat", [])),
    }
