"""My medicines, saved reports, share links and the administrators' usage report (D83)."""

from __future__ import annotations

import csv
import io
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import utc_now
from app.models import Report, SavedPill, User
from app.reports import seal
from app.routers.chat import to_result
from app.schemas import CitationRef
from tests.conftest import sign_in
from tests.test_admin import NEW_USER, user_id

DISCLAIMER = "Information uniquement, consultez un pharmacien ou un médecin."
QUESTION = "La warfarine interagit-elle avec le losartan ?"
ANSWER = "DDInter 2.0 classe cette interaction comme modérée [1]."
CITED = [{"n": 1, "title": "DDInter 2.0", "url": "https://ddinter2.scbdd.com/"}]


def excerpt(app: FastAPI, **changes: Any) -> dict[str, Any]:
    """A chat answer with the seal the server would have put on it."""
    body: dict[str, Any] = {"question": QUESTION, "answer": ANSWER, "citations": CITED}
    refs = [CitationRef(**c) for c in body["citations"]]
    body["signature"] = seal(app.state.answer_key, body["question"], body["answer"], refs)
    return {**body, **changes}


def saved(client: TestClient) -> list[int]:
    response = client.get("/api/my/medicines")
    assert response.status_code == 200, response.text
    return [item["class_id"] for item in response.json()["items"]]


def make_report(client: TestClient, **payload: Any) -> dict[str, Any]:
    response = client.post("/api/my/reports", json=payload)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# --- my medicines ---------------------------------------------------------------------------


def test_routes_require_sign_in(anonymous: TestClient, pharma: str) -> None:
    assert anonymous.get("/api/my/medicines").status_code == 401
    assert anonymous.post("/api/my/medicines", json={"class_id": 5}).status_code == 401
    assert anonymous.get("/api/my/reports").status_code == 401
    assert anonymous.post("/api/my/reports", json={"pills": [5, 7]}).status_code == 401


def test_medicines_are_kept_once_each(user: TestClient, pharma: str) -> None:
    assert saved(user) == []
    body = user.post("/api/my/medicines", json={"class_id": 7, "probability": 0.98}).json()
    (warfarin,) = body["items"]
    assert warfarin["name"] == "WARFARIN 5MG"
    assert warfarin["active_ingredients"] == ["warfarin"]
    assert warfarin["probability"] == 0.98
    assert {s["name"] for s in body["sources"]} == {"c3pi", "rxnav"}

    user.post("/api/my/medicines", json={"class_id": 5})  # picked by search: no probability
    user.post("/api/my/medicines", json={"class_id": 7, "probability": 0.5})  # again: once
    items = user.get("/api/my/medicines").json()["items"]
    assert [(i["class_id"], i["probability"]) for i in items] == [(7, 0.5), (5, None)]

    assert user.post("/api/my/medicines", json={"class_id": 4242}).status_code == 404
    assert [i["class_id"] for i in user.delete("/api/my/medicines/7").json()["items"]] == [5]
    assert user.delete("/api/my/medicines").status_code == 204
    assert saved(user) == []


def test_medicines_are_private(user: TestClient, admin: TestClient, pharma: str) -> None:
    user.post("/api/my/medicines", json={"class_id": 7})
    assert saved(admin) == []  # each account has its own list, admins included
    assert saved(user) == [7]


def test_the_list_holds_ten_medicines(app: FastAPI, user: TestClient, pharma: str) -> None:
    with app.state.session_factory() as db:  # ten rows, whatever the medicine tables hold
        uid = db.scalar(select(User.id).where(User.email == "user@gmail.com"))
        db.add_all(SavedPill(user_id=uid, class_id=1000 + n) for n in range(10))
        db.commit()
    response = user.post("/api/my/medicines", json={"class_id": 5})
    assert response.status_code == 409
    assert "10" in response.json()["detail"]


# --- reports --------------------------------------------------------------------------------


def test_report_checks_the_pills_again_and_keeps_a_snapshot(
    app: FastAPI, user: TestClient, pharma: str
) -> None:
    report = make_report(user, title="  Before the pharmacy  ", pills=[7, 5, 7])
    assert report["title"] == "Before the pharmacy"
    assert [p["name"] for p in report["pills"]] == ["WARFARIN 5MG", "HYZAAR 50MG"]  # once each
    assert report["highest_severity"] == "Moderate"
    (pair,) = report["interactions"]["pairs"]
    assert pair["interactions"][0]["severity"] == "Moderate"
    assert report["disclaimer"] == DISCLAIMER
    assert report["author"] == "Demo User"
    assert report["signature"] is None  # the demo account has no signature yet
    assert report["share"] is None
    assert report["chat"] == []

    # The snapshot stays as it was, whatever happens to the medicine tables afterwards.
    with app.state.session_factory() as db:
        stored = db.get(Report, report["id"])
        assert stored is not None
        assert stored.data["interactions"]["highest_severity"] == "Moderate"
    assert user.get(f"/api/my/reports/{report['id']}").json() == report

    page = user.get("/api/my/reports").json()
    assert page["total"] == 1
    (summary,) = page["items"]
    assert summary["pill_names"] == ["WARFARIN 5MG", "HYZAAR 50MG"]
    assert summary["ingredients"] == ["hydrochlorothiazide", "losartan", "warfarin"]
    assert summary["pairs_with_interaction"] == 1
    assert summary["chat_answers"] == 0


def test_report_needs_two_pills_or_an_answer(app: FastAPI, user: TestClient, pharma: str) -> None:
    assert user.post("/api/my/reports", json={"pills": [7]}).status_code == 422
    assert user.post("/api/my/reports", json={"pills": [7, 7]}).status_code == 422
    assert user.post("/api/my/reports", json={"pills": [7, 4242]}).status_code == 404
    report = make_report(user, pills=[7], chat=[excerpt(app)])
    assert report["interactions"] is None
    assert report["highest_severity"] is None
    assert report["chat"] == [{"question": QUESTION, "answer": ANSWER, "citations": CITED}]


def test_a_changed_answer_cannot_go_in_a_report(
    app: FastAPI, user: TestClient, pharma: str
) -> None:
    forged = excerpt(app)
    forged["answer"] = "Cette association est sûre."  # what the safety rules never allow
    response = user.post("/api/my/reports", json={"pills": [5, 7], "chat": [forged]})
    assert response.status_code == 422
    assert "Ask the question again" in response.json()["detail"]

    moved = excerpt(app)
    moved["citations"] = [{"n": 1, "title": "Another source", "url": "https://example.org/"}]
    assert user.post("/api/my/reports", json={"chat": [moved]}).status_code == 422
    assert (
        user.post("/api/my/reports", json={"chat": [excerpt(app, signature="0" * 64)]}).status_code
        == 422
    )
    assert user.get("/api/my/reports").json()["total"] == 0


def test_chat_answers_carry_a_seal_that_reports_accept(app: FastAPI) -> None:
    state: Any = {
        "question": QUESTION,
        "answer": ANSWER,
        "sources": [
            {"n": 1, "title": "DDInter 2.0", "url": "https://ddinter2.scbdd.com/"},
            {"n": 2, "title": "Not cited", "url": "https://example.org/"},
        ],
        "safety": {"action": "ok", "cited": [1]},
    }
    result = to_result(state, "fake", time.perf_counter(), app.state.answer_key)
    assert result.signature == excerpt(app)["signature"]  # only the cited source is sealed


def test_reports_are_private(
    app: FastAPI, user: TestClient, admin: TestClient, pharma: str
) -> None:
    report = make_report(user, pills=[5, 7])
    assert admin.get(f"/api/my/reports/{report['id']}").status_code == 404
    assert admin.delete(f"/api/my/reports/{report['id']}").status_code == 404
    assert admin.post(f"/api/my/reports/{report['id']}/share", json={}).status_code == 404
    assert admin.get("/api/my/reports").json()["total"] == 0
    assert user.delete(f"/api/my/reports/{report['id']}").status_code == 204
    assert user.get(f"/api/my/reports/{report['id']}").status_code == 404


# --- share links ----------------------------------------------------------------------------


def test_share_link_opens_the_report_without_signing_in(
    user: TestClient, anonymous: TestClient, pharma: str
) -> None:
    report = make_report(user, pills=[5, 7])
    created = user.post(f"/api/my/reports/{report['id']}/share", json={"days": 3}).json()
    token = created["token"]
    assert len(token) >= 30

    shared = anonymous.post("/api/shared", json={"token": token})
    assert shared.status_code == 200, shared.text
    assert shared.headers["cache-control"] == "no-store"
    body = shared.json()
    assert body["id"] == report["id"]
    assert body["highest_severity"] == "Moderate"
    assert body["disclaimer"] == DISCLAIMER
    assert "share" not in body and "email" not in shared.text.lower()
    anonymous.post("/api/shared", json={"token": token})

    share = user.get(f"/api/my/reports/{report['id']}").json()["share"]
    assert share["active"] is True
    assert share["views"] == 2

    # Only the hash is stored, and a wrong token says nothing about which reports exist.
    assert anonymous.post("/api/shared", json={"token": token[:-2] + "xx"}).status_code == 404


def test_new_link_replaces_the_old_one_and_stopping_ends_it(
    user: TestClient, anonymous: TestClient, pharma: str
) -> None:
    report = make_report(user, pills=[5, 7])
    first = user.post(f"/api/my/reports/{report['id']}/share", json={}).json()["token"]
    second = user.post(f"/api/my/reports/{report['id']}/share", json={}).json()["token"]
    assert anonymous.post("/api/shared", json={"token": first}).status_code == 404
    assert anonymous.post("/api/shared", json={"token": second}).status_code == 200

    assert user.delete(f"/api/my/reports/{report['id']}/share").status_code == 204
    assert anonymous.post("/api/shared", json={"token": second}).status_code == 404
    assert user.get(f"/api/my/reports/{report['id']}").json()["share"] is None


def test_expired_link_and_deleted_report_stop_working(
    app: FastAPI, user: TestClient, anonymous: TestClient, pharma: str
) -> None:
    report = make_report(user, pills=[5, 7])
    for days in (0, 31):  # one day to thirty
        response = user.post(f"/api/my/reports/{report['id']}/share", json={"days": days})
        assert response.status_code == 422
    token = user.post(f"/api/my/reports/{report['id']}/share", json={"days": 1}).json()["token"]
    with app.state.session_factory() as db:
        stored = db.get(Report, report["id"])
        assert stored is not None
        stored.share_expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
    assert anonymous.post("/api/shared", json={"token": token}).status_code == 404
    assert user.get(f"/api/my/reports/{report['id']}").json()["share"]["active"] is False

    token = user.post(f"/api/my/reports/{report['id']}/share", json={"days": 30}).json()["token"]
    user.delete(f"/api/my/reports/{report['id']}")
    assert anonymous.post("/api/shared", json={"token": token}).status_code == 404
    assert user.post(f"/api/my/reports/{report['id']}/share", json={}).status_code == 404


def test_deleting_an_account_deletes_its_medicines_and_reports(
    app: FastAPI,
    admin: TestClient,
    browser: Callable[[], TestClient],
    anonymous: TestClient,
    pharma: str,
) -> None:
    assert admin.post("/api/admin/users", json=NEW_USER).status_code == 201
    member = sign_in(browser(), {"email": NEW_USER["email"], "password": NEW_USER["password"]})
    member.post("/api/my/medicines", json={"class_id": 7})
    report = make_report(member, pills=[5, 7])
    token = member.post(f"/api/my/reports/{report['id']}/share", json={}).json()["token"]

    assert admin.delete(f"/api/admin/users/{user_id(admin, NEW_USER['email'])}").status_code == 204
    assert anonymous.post("/api/shared", json={"token": token}).status_code == 404
    with app.state.session_factory() as db:
        assert db.get(Report, report["id"]) is None


def test_report_events_hold_counts_only(
    app: FastAPI, user: TestClient, admin: TestClient, pharma: str
) -> None:
    report = make_report(user, pills=[5, 7], chat=[excerpt(app)])
    user.post(f"/api/my/reports/{report['id']}/share", json={"days": 5})
    user.delete(f"/api/my/reports/{report['id']}/share")
    user.delete(f"/api/my/reports/{report['id']}")
    events = admin.get("/api/admin/activity", params={"q": "user@gmail.com"}).json()["items"]
    by_action = {e["action"]: e["details"] for e in events}
    assert by_action["report_create"] == {"items": 2, "answers": 1}
    assert by_action["report_share"] == {"days": 5}
    assert "report_unshare" in by_action and "report_delete" in by_action
    text = str(events).lower()
    assert "warfarin" not in text and "hyzaar" not in text and "losartan" not in text


# --- usage report and CSV exports -----------------------------------------------------------


def test_usage_counts_each_day(user: TestClient, admin: TestClient, pharma: str) -> None:
    make_report(user, pills=[5, 7])
    assert user.get("/api/admin/usage").status_code == 403
    body = admin.get("/api/admin/usage", params={"days": 7, "tz": 60}).json()
    assert len(body["days"]) == 7
    today = body["days"][-1]
    assert today["counts"]["sign_in"] >= 2  # the demo user and the administrator
    assert today["counts"]["report_create"] == 1
    assert today["active_users"] == 2
    assert body["totals"]["report_create"] == 1
    assert body["active_users"] == 2
    assert body["reports_saved"] == 1
    assert body["shared_now"] == 0
    assert admin.get("/api/admin/usage", params={"days": 0}).status_code == 422


def test_failed_sign_ins_are_not_activity(
    admin: TestClient, browser: Callable[[], TestClient]
) -> None:
    browser().post("/api/auth/login", json={"email": "user@gmail.com", "password": "nope"})
    body = admin.get("/api/admin/usage", params={"days": 1}).json()
    assert body["totals"]["sign_in_failed"] == 1
    assert body["active_users"] == 1  # only the administrator


def read_csv(response: Any) -> list[dict[str, str]]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    return list(csv.DictReader(io.StringIO(response.text.lstrip("﻿"))))


def test_users_export(admin: TestClient, user: TestClient) -> None:
    assert user.get("/api/admin/export/users.csv").status_code == 403
    risky = {**NEW_USER, "full_name": '=HYPERLINK("http://x")'}
    assert admin.post("/api/admin/users", json=risky).status_code == 201
    rows = read_csv(admin.get("/api/admin/export/users.csv"))
    email = NEW_USER["email"].lower()
    assert {r["email"] for r in rows} >= {"admin@gmail.com", "user@gmail.com", email}
    assert "password" not in ",".join(rows[0].keys())
    (created,) = [r for r in rows if r["email"] == email]
    assert created["full_name"].startswith("'=")  # never run as a formula by a spreadsheet


def test_activity_export_uses_the_filters_and_is_logged(
    admin: TestClient, user: TestClient
) -> None:
    rows = read_csv(admin.get("/api/admin/export/activity.csv", params={"action": "sign_in"}))
    assert rows and {r["action"] for r in rows} == {"sign_in"}
    events = admin.get("/api/admin/activity", params={"action": "data_export"}).json()["items"]
    assert events[0]["details"] == {"table": "activity", "rows": len(rows)}
