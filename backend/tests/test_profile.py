"""The signed-in user's own profile: details, photo and signature."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.config import Settings
from app.main import create_app
from tests.conftest import USER, sign_in


def png(width: int, height: int, channels: int = 3) -> bytes:
    image = np.full((height, width, channels), 200, dtype=np.uint8)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def test_update_phone_and_clear_it(user: TestClient) -> None:
    response = user.patch("/api/auth/me", json={"phone": "  +216 20   123 456 "})
    assert response.status_code == 200, response.text
    assert response.json()["phone"] == "+216 20 123 456"
    assert user.patch("/api/auth/me", json={"phone": "call me"}).status_code == 422
    assert user.patch("/api/auth/me", json={"phone": "12"}).status_code == 422
    assert user.patch("/api/auth/me", json={"phone": ""}).json()["phone"] is None


def test_partial_update_keeps_other_fields(user: TestClient) -> None:
    user.patch("/api/auth/me", json={"phone": "+33 6 12 34 56 78"})
    me = user.patch("/api/auth/me", json={"full_name": "New Name"}).json()
    assert (me["full_name"], me["phone"]) == ("New Name", "+33 6 12 34 56 78")


def test_changing_email_needs_the_current_password(
    user: TestClient, browser: Callable[[], TestClient]
) -> None:
    new_email = {"email": "New.Address@Mail.com"}
    assert user.patch("/api/auth/me", json=new_email).status_code == 400
    wrong = user.patch("/api/auth/me", json={**new_email, "current_password": "nope"})
    assert wrong.status_code == 400
    taken = user.patch(
        "/api/auth/me", json={"email": "admin@gmail.com", "current_password": USER["password"]}
    )
    assert taken.status_code == 409
    ok = user.patch("/api/auth/me", json={**new_email, "current_password": USER["password"]})
    assert ok.status_code == 200
    assert ok.json()["email"] == "new.address@mail.com"
    sign_in(browser(), {"email": "new.address@mail.com", "password": USER["password"]})


def test_same_email_needs_no_password(user: TestClient) -> None:
    response = user.patch("/api/auth/me", json={"email": USER["email"], "full_name": "Same"})
    assert response.status_code == 200


def test_photo_upload_is_cropped_and_served(user: TestClient) -> None:
    response = user.put(
        "/api/auth/me/photo", files={"image": ("me.png", png(800, 500), "image/png")}
    )
    assert response.status_code == 200, response.text
    url = response.json()["photo_url"]
    assert url.startswith(f"/api/users/{response.json()['id']}/photo?v=")
    served = user.get(url)
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/jpeg"
    image = cv2.imdecode(np.frombuffer(served.content, np.uint8), cv2.IMREAD_COLOR)
    assert image.shape[:2] == (256, 256)

    assert user.delete("/api/auth/me/photo").json()["photo_url"] is None
    assert user.get(url).status_code == 404


def test_photo_rejects_files_that_are_not_images(user: TestClient) -> None:
    fake = user.put("/api/auth/me/photo", files={"image": ("x.png", b"not an image", "image/png")})
    assert fake.status_code == 415
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
    typed = user.put("/api/auth/me/photo", files={"image": ("x.svg", svg, "image/svg+xml")})
    assert typed.status_code == 415
    tiny = user.put("/api/auth/me/photo", files={"image": ("x.png", png(10, 10), "image/png")})
    assert tiny.status_code == 415


def test_signature_keeps_transparency(user: TestClient) -> None:
    response = user.put(
        "/api/auth/me/signature",
        files={"image": ("sig.png", png(2400, 400, channels=4), "image/png")},
    )
    assert response.status_code == 200, response.text
    served = user.get(response.json()["signature_url"])
    assert served.headers["content-type"] == "image/png"
    assert served.headers["cache-control"] == "no-store"
    image = cv2.imdecode(np.frombuffer(served.content, np.uint8), cv2.IMREAD_UNCHANGED)
    assert image.shape == (200, 1200, 4)  # shrunk to fit 1200 x 400, alpha kept
    assert user.delete("/api/auth/me/signature").json()["signature_url"] is None


def test_images_are_private_except_to_administrators(
    user: TestClient, admin: TestClient, browser: Callable[[], TestClient]
) -> None:
    body = user.put(
        "/api/auth/me/photo", files={"image": ("me.png", png(64, 64), "image/png")}
    ).json()
    url = body["photo_url"]
    assert admin.get(url).status_code == 200
    assert browser().get(url).status_code == 401

    other = browser()
    other.post(
        "/api/auth/signup",
        json={"email": "eve@mail.com", "full_name": "Eve", "password": "s3cret-pass"},
    )
    assert other.get(url).status_code == 404


def test_an_older_database_gains_the_new_columns(tmp_path: Path, processed_dir: Path) -> None:
    url = f"sqlite:///{(tmp_path / 'old.db').as_posix()}"
    engine = create_engine(url)
    with engine.begin() as connection:  # the users table as it was before phone and photo
        connection.execute(
            text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, email VARCHAR(254),"
                " full_name VARCHAR(120), password_hash VARCHAR(255), role VARCHAR(16),"
                " is_active BOOLEAN, created_at DATETIME, last_login_at DATETIME)"
            )
        )
    engine.dispose()

    settings = Settings(
        _env_file=None,
        database_url=url,
        processed_dir=processed_dir,
        pharma_database_url=f"sqlite:///{(tmp_path / 'pharma.db').as_posix()}",
        rag_warmup=False,
    )
    with TestClient(create_app(settings)) as client:
        sign_in(client, USER)
        response = client.patch("/api/auth/me", json={"phone": "+216 20 123 456"})
        assert response.status_code == 200, response.text
