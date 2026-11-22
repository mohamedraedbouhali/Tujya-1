"""POST /api/scan: one photo in, every detected pill out with its top-5 identifications.

Sign-in required, like the catalog: the demo uses the demo account (decision D46).
"""

from __future__ import annotations

import time
from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app import model_card
from app.activity import log_event
from app.annotate import annotate, to_png
from app.config import Settings
from app.deps import CurrentUser, PharmaSession, SettingsDep, get_current_user
from app.medicines import DISCLAIMER, PharmaUnavailable, pill_infos, sources
from app.models import Action
from app.scanner import (
    InvalidImage,
    ModelsMissing,
    PillScanner,
    ScannerHolder,
    decode_image,
    has_gpu,
    installed_providers,
)
from app.schemas import (
    ClassEntry,
    ModelMetadata,
    NormalizedBox,
    PillCandidate,
    PixelBox,
    ProvidersInfo,
    ScannedPill,
    ScanResult,
    ScanTimings,
    SourceOut,
    VisionModelCard,
)

router = APIRouter(prefix="/api", tags=["scan"], dependencies=[Depends(get_current_user)])
# `GET /api/model/metadata` describes the deployed model, not a user's data: no sign-in,
# like `GET /api/health`, so the model card can be read straight from Swagger.
public_router = APIRouter(prefix="/api", tags=["scan"])

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
NO_PILL = "Aucun comprimé détecté. Essayez une photo nette, le comprimé entier, sur un fond uni."


def pharma_unavailable() -> HTTPException:
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "The medicine tables are not loaded. Run `python -m app.pharma_loader` (docs/INFRA.md).",
    )


def get_scanner(request: Request) -> PillScanner:
    holder: ScannerHolder = request.app.state.scanner
    try:
        return holder.get()
    except ModelsMissing as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


def _decode(data: bytes, settings: Settings) -> np.ndarray:
    try:
        return decode_image(data, max_pixels=settings.scan_max_pixels)
    except InvalidImage as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc


def _run(scanner: PillScanner, data: bytes, settings: Settings, db: Session) -> ScanResult:
    """Blocking part (decode, ONNX Runtime, database), run in the thread pool."""
    return _analyse(scanner, _decode(data, settings), settings, db)


def _analyse(
    scanner: PillScanner, image: np.ndarray, settings: Settings, db: Session
) -> ScanResult:
    output = scanner.scan(image)
    try:
        infos = pill_infos(db, (c for d in output.detections for c in d.classes))
        cited = sources(db, ["c3pi", "rxnav"])
    except PharmaUnavailable as exc:
        raise pharma_unavailable() from exc

    pills = []
    for detection in output.detections:
        candidates = []
        for class_id, probability in zip(detection.classes, detection.probabilities, strict=True):
            info = infos.get(class_id)
            candidates.append(
                PillCandidate(
                    class_id=class_id,
                    name=info.name if info else f"class {class_id}",
                    generic_name=info.generic_name if info else "",
                    active_ingredients=info.ingredients if info else [],
                    probability=min(1.0, max(0.0, probability)),
                )
            )
        x1, y1, x2, y2 = detection.box
        pills.append(
            ScannedPill(
                box=PixelBox(x1=x1, y1=y1, x2=x2, y2=y2),
                box_normalized=NormalizedBox(
                    x1=x1 / output.width,
                    y1=y1 / output.height,
                    x2=x2 / output.width,
                    y2=y2 / output.height,
                ),
                detection_confidence=min(1.0, detection.confidence),
                candidates=candidates,
                needs_confirmation=candidates[0].probability < settings.scan_confirm_threshold,
            )
        )
    total = output.detection_ms + output.classification_ms
    return ScanResult(
        image_width=output.width,
        image_height=output.height,
        inference_ms=round(total, 1),
        timings=ScanTimings(
            detection_ms=round(output.detection_ms, 1),
            classification_ms=round(output.classification_ms, 1),
            total_ms=round(total, 1),
        ),
        confirm_threshold=settings.scan_confirm_threshold,
        pills=pills,
        message=None if pills else NO_PILL,
        models=output.models,
        sources=[SourceOut.model_validate(s) for s in cited],
        disclaimer=DISCLAIMER,
    )


UPLOAD_ERRORS = {
    413: {"description": "Image larger than the upload limit"},
    415: {"description": "Not a JPEG, PNG or WebP image"},
    503: {"description": "Models or medicine tables not available"},
}


@router.post(
    "/predict",
    response_model=ScanResult,
    summary="Predict (alias of POST /api/scan)",
    responses=UPLOAD_ERRORS,
)
@router.post("/scan", response_model=ScanResult, responses=UPLOAD_ERRORS)
async def scan(
    image: Annotated[UploadFile, File(description="JPEG, PNG or WebP photo of the pills")],
    request: Request,
    settings: SettingsDep,
    db: PharmaSession,
    user: CurrentUser,
    live: Annotated[
        bool, Query(description="A live webcam preview frame: not recorded in the activity log")
    ] = False,
) -> ScanResult:
    """Detect every pill in the photo, then identify each one among the 150 C3PI classes.

    Identification is a suggestion: `needs_confirmation` is true when the most probable
    class is below `confirm_threshold`, and the app then asks the user to pick from the
    top-5 or search the list (GET /api/pills).
    """
    if image.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Send a JPEG, PNG or WebP image."
        )
    data = await image.read(settings.scan_max_bytes + 1)
    if len(data) > settings.scan_max_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"The image is larger than {settings.scan_max_bytes // (1024 * 1024)} MB.",
        )
    scanner = await run_in_threadpool(get_scanner, request)
    result = await run_in_threadpool(_run, scanner, data, settings, db)
    if not live:  # the webcam preview sends about one frame a second
        await run_in_threadpool(log_event, request, user.id, Action.SCAN, pills=len(result.pills))
    return result


def _draw(scanner: PillScanner, data: bytes, settings: Settings, db: Session) -> tuple[bytes, int]:
    """The annotated PNG and how many pills it shows; decodes the photo only once."""
    image = _decode(data, settings)
    result = _analyse(scanner, image, settings, db)
    return to_png(annotate(image, result)), len(result.pills)


@public_router.post(
    "/predict/visualize",
    response_class=Response,
    dependencies=[Depends(get_current_user)],
    summary="The photo with one coloured box, name and score per pill",
    responses={
        200: {"content": {"image/png": {}}, "description": "The annotated photo"},
        **UPLOAD_ERRORS,
    },
)
async def predict_visualize(
    image: Annotated[UploadFile, File(description="JPEG, PNG or WebP photo of the pills")],
    request: Request,
    settings: SettingsDep,
    db: PharmaSession,
    user: CurrentUser,
) -> Response:
    """The same inference as `POST /api/scan`, returned as an image instead of JSON.

    Every detected pill gets a box in a colour derived from its class, captioned with the
    most probable product and its probability; a pill below `confirm_threshold` is marked
    "(to confirm)". The inference time is in the `X-Inference-Ms` header and in the banner.
    """
    if image.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Send a JPEG, PNG or WebP image."
        )
    data = await image.read(settings.scan_max_bytes + 1)
    if len(data) > settings.scan_max_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"The image is larger than {settings.scan_max_bytes // (1024 * 1024)} MB.",
        )
    started = time.perf_counter()
    scanner = await run_in_threadpool(get_scanner, request)
    png, found = await run_in_threadpool(_draw, scanner, data, settings, db)
    elapsed = (time.perf_counter() - started) * 1000
    await run_in_threadpool(log_event, request, user.id, Action.SCAN, pills=found)
    return Response(
        png,
        media_type="image/png",
        headers={
            "X-Pills": str(found),
            "X-Inference-Ms": f"{elapsed:.1f}",
            "Cache-Control": "no-store",
        },
    )


def _card(
    task: str, meta: dict[str, Any], session: Any, manifest: dict[str, Any]
) -> VisionModelCard:
    origin = manifest.get(task, {})
    run_id = origin.get("run_id")
    return VisionModelCard(
        task=task,  # type: ignore[arg-type]
        registered_model=origin.get("registered_model"),
        version=origin.get("version"),
        run_id=run_id,
        architecture=model_card.architecture(meta),
        exported_by=f"Ultralytics {meta.get('version', '')}".strip(),
        input_shape=[int(d) if isinstance(d, int) else -1 for d in session.get_inputs()[0].shape],
        output_shape=[int(d) if isinstance(d, int) else -1 for d in session.get_outputs()[0].shape],
        n_classes=len(meta.get("names") or {}),
        validation_metrics=model_card.metrics_for(run_id),
        training=model_card.training_for(run_id),
    )


@public_router.get(
    "/model/metadata",
    response_model=ModelMetadata,
    summary="Characteristics of the deployed models: architecture, metrics, classes",
    responses={503: {"description": "The ONNX files are not in the model directory"}},
)
async def model_metadata(
    request: Request, settings: SettingsDep, db: PharmaSession
) -> ModelMetadata:
    """What is actually being served: the two ONNX models, where each came from in the
    MLflow registry, how it scored on the test split, and the 150 classes it can return.

    The scores are attached to the MLflow run id of the file on disk, so publishing another
    version leaves `validation_metrics` empty rather than reporting the old numbers.
    """
    scanner = await run_in_threadpool(get_scanner, request)
    try:
        infos = await run_in_threadpool(pill_infos, db, scanner.class_ids)
    except PharmaUnavailable:
        infos = {}  # the model card still describes the models without the medicine tables
    classes = [
        ClassEntry(
            class_id=class_id,
            name=infos[class_id].name if class_id in infos else "",
            generic_name=infos[class_id].generic_name if class_id in infos else "",
        )
        for class_id in scanner.class_ids
    ]
    return ModelMetadata(
        pipeline=model_card.PIPELINE,
        models=[
            _card("detect", scanner.det_meta, scanner.detector, scanner.manifest),
            _card("classify", scanner.cls_meta, scanner.classifier, scanner.manifest),
        ],
        n_classes=len(scanner.class_ids),
        classes=classes,
        confirm_threshold=settings.scan_confirm_threshold,
        end_to_end=dict(model_card.END_TO_END),
        providers=ProvidersInfo(
            available=installed_providers(),
            requested=settings.onnx_providers,
            gpu=has_gpu(),
        ),
        disclaimer=DISCLAIMER,
    )
