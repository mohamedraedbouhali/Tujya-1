"""The endpoints the course specification asks for: health, model card, visualised predict.

Same tiny fake ONNX models as test_scan.py, so no real weights are needed.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.annotate import annotate, class_color, to_png
from app.schemas import NormalizedBox, PillCandidate, PixelBox, ScannedPill, ScanResult, ScanTimings
from tests.fake_models import write_models
from tests.test_scan import BOXES, NAMES, photo


@pytest.fixture
def models(app: FastAPI) -> Path:
    directory: Path = app.state.settings.models_dir
    write_models(directory, BOXES, NAMES)
    return directory


# --------------------------------------------------------------------------- health


def test_health_is_public_and_reports_the_hardware(anonymous: TestClient) -> None:
    body = anonymous.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["api_version"]
    assert isinstance(body["gpu"], bool)
    assert "CPUExecutionProvider" in body["providers"]["available"]
    assert body["providers"]["gpu"] == body["gpu"]


def test_health_reports_missing_models_without_failing(anonymous: TestClient) -> None:
    body = anonymous.get("/api/health").json()
    assert body["models"]["detect"]["present"] is False
    assert body["models"]["classify"]["file"] == "classifier.onnx"
    assert body["models_loaded"] is False


def test_health_sees_the_published_models(anonymous: TestClient, models: Path) -> None:
    body = anonymous.get("/api/health").json()
    assert body["models"]["detect"]["present"] is True
    assert body["models"]["classify"]["present"] is True
    # Reading health must never pull the weights into memory.
    assert body["models_loaded"] is False


def test_health_shows_the_models_once_they_are_loaded(
    user: TestClient, anonymous: TestClient, models: Path, pharma: str
) -> None:
    assert user.post("/api/scan", files={"image": ("a.png", photo(), "image/png")}).status_code
    assert anonymous.get("/api/health").json()["models_loaded"] is True


# --------------------------------------------------------------------- model metadata


def test_model_metadata_needs_the_models(anonymous: TestClient) -> None:
    assert anonymous.get("/api/model/metadata").status_code == 503


def test_model_metadata_describes_both_models(
    anonymous: TestClient, models: Path, pharma: str
) -> None:
    response = anonymous.get("/api/model/metadata")
    assert response.status_code == 200, response.text
    body = response.json()
    tasks = {model["task"]: model for model in body["models"]}
    assert set(tasks) == {"detect", "classify"}
    assert tasks["detect"]["input_shape"] == [1, 3, 64, 64]
    assert tasks["classify"]["output_shape"] == [1, len(NAMES)]
    assert tasks["classify"]["n_classes"] == len(NAMES)
    assert body["n_classes"] == len(NAMES)
    assert [entry["class_id"] for entry in body["classes"]] == [int(n) for n in NAMES]
    assert body["confirm_threshold"] > 0
    assert body["disclaimer"]


def test_model_metadata_does_not_invent_metrics_for_an_unknown_run(
    anonymous: TestClient, models: Path, pharma: str
) -> None:
    """The fake manifest has no run id, so no score may be attributed to these files."""
    body = anonymous.get("/api/model/metadata").json()
    for model in body["models"]:
        assert model["validation_metrics"] == {}
        assert model["training"] == {}


def test_model_metadata_survives_missing_medicine_tables(
    anonymous: TestClient, models: Path
) -> None:
    body = anonymous.get("/api/model/metadata").json()
    assert body["n_classes"] == len(NAMES)
    assert all(entry["name"] == "" for entry in body["classes"])


# ------------------------------------------------------------------- predict (alias)


def test_predict_is_the_same_endpoint_as_scan(user: TestClient, models: Path, pharma: str) -> None:
    files = {"image": ("a.png", photo(), "image/png")}
    scan = user.post("/api/scan", files=files).json()
    predict = user.post("/api/predict", files=files).json()
    assert [p["candidates"][0]["class_id"] for p in predict["pills"]] == [
        p["candidates"][0]["class_id"] for p in scan["pills"]
    ]
    assert predict["confirm_threshold"] == scan["confirm_threshold"]


def test_predict_is_in_the_openapi_schema(anonymous: TestClient) -> None:
    paths = anonymous.get("/openapi.json").json()["paths"]
    for required in ("/api/predict", "/api/predict/visualize", "/api/model/metadata"):
        assert required in paths, required


# ----------------------------------------------------------------- predict/visualize


def test_visualize_returns_an_annotated_png(user: TestClient, models: Path, pharma: str) -> None:
    response = user.post("/api/predict/visualize", files={"image": ("a.png", photo(), "image/png")})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert response.headers["X-Pills"] == "2"
    assert float(response.headers["X-Inference-Ms"]) >= 0
    drawn = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
    assert drawn.shape == (100, 200, 3)
    # The original photo is white outside the two pills; the boxes must have changed it.
    assert not np.array_equal(drawn, cv2.imdecode(np.frombuffer(photo(), np.uint8), 1))


def test_visualize_requires_sign_in(anonymous: TestClient, models: Path) -> None:
    response = anonymous.post(
        "/api/predict/visualize", files={"image": ("a.png", photo(), "image/png")}
    )
    assert response.status_code == 401


def test_visualize_refuses_what_is_not_an_image(
    user: TestClient, models: Path, pharma: str
) -> None:
    junk = {"image": ("a.txt", b"hello", "text/plain")}
    assert user.post("/api/predict/visualize", files=junk).status_code == 415
    broken = {"image": ("a.png", b"not a png", "image/png")}
    assert user.post("/api/predict/visualize", files=broken).status_code == 415


def test_visualize_answers_503_without_models(user: TestClient, pharma: str) -> None:
    response = user.post("/api/predict/visualize", files={"image": ("a.png", photo(), "image/png")})
    assert response.status_code == 503


# ------------------------------------------------------------------------- annotate


def _result(*, probability: float = 0.95, class_id: int = 7) -> ScanResult:
    pill = ScannedPill(
        box=PixelBox(x1=10, y1=10, x2=60, y2=60),
        box_normalized=NormalizedBox(x1=0.05, y1=0.1, x2=0.3, y2=0.6),
        detection_confidence=0.9,
        candidates=[
            PillCandidate(
                class_id=class_id,
                name="Paracétamol 500 mg",
                generic_name="acetaminophen",
                active_ingredients=["acetaminophen"],
                probability=probability,
            )
        ],
        needs_confirmation=probability < 0.85,
    )
    return ScanResult(
        image_width=200,
        image_height=100,
        inference_ms=12.0,
        timings=ScanTimings(detection_ms=8.0, classification_ms=4.0, total_ms=12.0),
        confirm_threshold=0.85,
        pills=[pill],
        models={},
        sources=[],
        disclaimer="info only",
    )


def test_every_class_gets_its_own_colour() -> None:
    colours = {class_color(class_id) for class_id in range(150)}
    assert len(colours) > 140  # a few near-duplicates are fine, a single colour is not
    assert class_color(7) == class_color(7)  # stable across calls


def test_annotate_draws_inside_the_image_and_keeps_its_size() -> None:
    image = np.full((100, 200, 3), 255, dtype=np.uint8)
    drawn = annotate(image, _result())
    assert drawn.shape == image.shape
    assert np.array_equal(image, np.full((100, 200, 3), 255, dtype=np.uint8))  # not in place
    assert (drawn != 255).any()
    assert to_png(drawn)[:8] == b"\x89PNG\r\n\x1a\n"


def test_a_low_score_is_marked_to_confirm() -> None:
    """Only a smoke test: the caption is pixels, so we check the two renders differ."""
    image = np.full((100, 200, 3), 255, dtype=np.uint8)
    sure = annotate(image, _result(probability=0.99))
    unsure = annotate(image, _result(probability=0.40))
    assert not np.array_equal(sure, unsure)
