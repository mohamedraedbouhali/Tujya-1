"""The activity log administrators read: GET /api/admin/activity (D82)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.activity import prune_activity
from app.db import utc_now
from app.models import ActivityEvent
from tests.conftest import ADMIN, USER, sign_in
from tests.fake_models import write_models
from tests.test_admin import NEW_USER, user_id
from tests.test_scan import BOXES, NAMES, photo


@pytest.fixture
def scan_models(app: FastAPI) -> Path:
    directory: Path = app.state.settings.models_dir
    write_models(directory, BOXES, NAMES)
    return directory


def activity(admin: TestClient, **params: Any) -> dict[str, Any]:
    response = admin.get("/api/admin/activity", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def actions(admin: TestClient, **params: Any) -> list[str]:
    """Newest first, like the page shows them."""
    return [event["action"] for event in activity(admin, **params)["items"]]


def test_only_administrators_read_the_activity(user: TestClient, anonymous: TestClient) -> None:
    assert user.get("/api/admin/activity").status_code == 403
    assert anonymous.get("/api/admin/activity").status_code == 401


def test_sign_ins_failures_and_sign_out(
    admin: TestClient, browser: Callable[[], TestClient]
) -> None:
    me = user_id(admin, USER["email"])
    visitor = browser()
    assert visitor.post("/api/auth/login", json={**USER, "password": "wrong"}).status_code == 401
    # An unknown email belongs to nobody: nothing to record.
    assert visitor.post("/api/auth/login", json={**USER, "email": "x@y.com"}).status_code == 401
    sign_in(visitor, USER)
    visitor.post("/api/auth/logout")

    assert actions(admin, user_id=me) == ["sign_out", "sign_in", "sign_in_failed"]
    event = activity(admin, user_id=me)["items"][1]
    assert event["user"]["email"] == USER["email"]
    assert event["ip"] == "testclient" and event["user_agent"] == "testclient"
    assert "password_hash" not in event["user"]

    admin.patch(f"/api/admin/users/{me}", json={"is_active": False})
    assert visitor.post("/api/auth/login", json=USER).status_code == 403
    assert actions(admin, user_id=me)[0] == "sign_in_blocked"


def test_sign_up_is_recorded(admin: TestClient, anonymous: TestClient) -> None:
    created = anonymous.post("/api/auth/signup", json=NEW_USER)
    assert created.status_code == 201
    assert actions(admin, user_id=created.json()["id"]) == ["sign_up"]


def test_profile_changes_record_what_changed_not_the_values(
    admin: TestClient, user: TestClient
) -> None:
    me = user_id(admin, USER["email"])
    user.patch("/api/auth/me", json={"full_name": "Demo User", "phone": ""})  # no change
    user.patch("/api/auth/me", json={"full_name": "Someone Else", "phone": "+216 20 123 456"})
    user.post(
        "/api/auth/me/password",
        json={"current_password": USER["password"], "new_password": "another-pass"},
    )
    user.delete("/api/auth/me/photo")  # there was no photo: nothing happened

    events = activity(admin, user_id=me)["items"]
    assert [e["action"] for e in events] == ["password_change", "profile_update", "sign_in"]
    assert events[1]["details"] == {"fields": ["name", "phone"]}
    assert "+216" not in str(events)


def test_administrator_actions_name_their_target(admin: TestClient, user: TestClient) -> None:
    target = user_id(admin, USER["email"])
    admin.patch(f"/api/admin/users/{target}", json={"role": "admin", "full_name": "Demo User"})
    admin.patch(f"/api/admin/users/{target}", json={"is_active": False})
    admin.post(f"/api/admin/users/{target}/password", json={"new_password": "fresh-pass-1"})

    events = activity(admin, user_id=target)["items"]
    assert [e["action"] for e in events] == [
        "password_reset",
        "user_update",
        "user_update",
        "sign_in",
    ]
    # Done by the administrator, about the user: both are on the user's timeline.
    assert {e["user"]["email"] for e in events[:3]} == {ADMIN["email"]}
    assert {e["target_id"] for e in events[:3]} == {target}
    assert events[1]["details"]["changes"] == {"active": False}
    assert events[2]["details"]["changes"] == {"role": "admin"}  # the name did not change
    assert events[2]["details"]["email"] == USER["email"]


def test_deleting_an_account_deletes_its_activity_but_not_the_deletion(
    admin: TestClient, user: TestClient
) -> None:
    created = admin.post("/api/admin/users", json=NEW_USER).json()
    bob = sign_in(
        TestClient(admin.app), {"email": "bob@mail.com", "password": NEW_USER["password"]}
    )
    bob.get("/api/auth/me")
    assert admin.delete(f"/api/admin/users/{created['id']}").status_code == 204

    events = activity(admin, user_id=created["id"])["items"]
    assert [e["action"] for e in events] == ["user_delete", "user_create"]  # bob's sign-in is gone
    assert events[0]["details"] == {"name": "Bob Stone", "email": "bob@mail.com"}
    assert events[1]["details"]["role"] == "user"


def test_filters_counts_and_pages(admin: TestClient, browser: Callable[[], TestClient]) -> None:
    for _ in range(3):
        sign_in(browser(), USER)
    everything = activity(admin)
    assert everything["counts"] == {"sign_in": 4}  # the fixture's admin, then 3 users
    assert everything["total"] == 4

    only_failures = activity(admin, action=["sign_in_failed", "sign_out"])
    assert only_failures["total"] == 0
    assert only_failures["counts"] == {"sign_in": 4}  # counts ignore the action filter

    assert activity(admin, q="USER@gmail")["total"] == 3
    assert activity(admin, q="%")["total"] == 0  # searched literally
    page = activity(admin, page=2, page_size=2)
    assert (page["total"], page["page"], len(page["items"])) == (4, 2, 2)
    assert activity(admin, days=1)["total"] == 4
    assert admin.get("/api/admin/activity", params={"action": "dance"}).status_code == 422
    assert admin.get("/api/admin/activity", params={"page_size": 500}).status_code == 422


def test_old_events_are_pruned(admin: TestClient, user: TestClient) -> None:
    factory = admin.app.state.session_factory
    with factory() as db:
        old = db.query(ActivityEvent).order_by(ActivityEvent.id).first()
        assert old is not None
        old.created_at = utc_now() - timedelta(days=400)
        db.commit()
        assert prune_activity(db, 0) == 0  # 0 keeps everything
        assert prune_activity(db, 180) == 1
    assert activity(admin)["total"] == 1


def test_scans_checks_and_questions_hold_counts_only(
    admin: TestClient,
    user: TestClient,
    scan_models: Path,
    pharma: str,
) -> None:
    scanned = user.post("/api/scan", files={"image": ("a.png", photo(), "image/png")})
    assert scanned.status_code == 200, scanned.text
    live = user.post(
        "/api/scan", params={"live": "true"}, files={"image": ("a.png", photo(), "image/png")}
    )
    assert live.status_code == 200
    checked = user.post("/api/interactions", json={"pills": [5, 7]})
    assert checked.status_code == 200

    me = user_id(admin, USER["email"])
    events = activity(admin, user_id=me)["items"]
    assert [e["action"] for e in events] == ["interactions", "scan", "sign_in"]  # no live frame
    assert events[1]["details"] == {"pills": len(scanned.json()["pills"])}
    assert events[0]["details"] == {"items": 2}
    # No pill or ingredient name reaches the log.
    names = {c["name"] for p in scanned.json()["pills"] for c in p["candidates"]}
    assert names and not any(name in str(events) for name in names)
