"""What `GET /api/model/metadata` reports about the two served vision models.

Three sources are combined:

- `models/models.json`, written by `python -m tujya_vision.publish`: which MLflow
  registered model and version each ONNX file comes from;
- the ONNX metadata Ultralytics embeds in the file itself (architecture, task, input size,
  class names, stride, exporter version), read through the loaded ONNX Runtime session;
- `MEASURED` below: the test scores of the training runs, copied from the `summary.json`
  of each run in `vision/runs/` (the run directories are not mounted in the container).

`MEASURED` is keyed by **MLflow run id**, so a score is only ever attached to the exact run
whose file is being served. Publishing another version makes `validation_metrics` empty
instead of reporting the previous run's numbers.
"""

from __future__ import annotations

import re
from typing import Any

# Test metrics of the published runs. Sources, on the machine that trained them:
#   vision/runs/classify-20261101-171828/summary.json
#   vision/runs/detect-20261101-194254/summary.json
# End-to-end figures (the whole chain on the 600 test photos): docs/VISION.md, measured
# with `python backend/scripts/evaluate_scan.py --split test`.
MEASURED: dict[str, dict[str, float]] = {
    # tujya-pill-classifier version 1, YOLO11s-cls, 40 epochs
    "9e118a986ca8420383754100514d54a1": {
        "test_top1": 0.9389,
        "test_top5": 0.9762,
        "test_images": 589,
        "test_classes": 148,
        "onnx_top1_agreement": 1.0,
    },
    # tujya-pill-detector version 1, YOLO11n, 30 epochs, 640 px
    "351bf9233a214f78ac0a3deab83959e0": {
        "test_mAP50": 0.9695,
        "test_mAP50_95": 0.8498,
        "test_precision": 0.9416,
        "test_recall": 0.9511,
        "onnx_mean_box_iou": 0.9922,
    },
}

TRAINING: dict[str, dict[str, Any]] = {
    "9e118a986ca8420383754100514d54a1": {
        "weights": "yolo11s-cls.pt",
        "pretrained_on": "ImageNet",
        "epochs": 40,
        "imgsz": 224,
        "batch": 32,
        "train_images": 2962,
        "val_images": 562,
        "test_images": 589,
    },
    "351bf9233a214f78ac0a3deab83959e0": {
        "weights": "yolo11n.pt",
        "pretrained_on": "COCO",
        "epochs": 30,
        "imgsz": 640,
        "batch": 8,
        "train_images": 2345,
        "val_images": 478,
        "test_images": 483,
    },
}

END_TO_END = {
    "photos": 600,
    "pill_detected": 0.985,
    "top1": 0.893,
    "top5": 0.958,
    "note": (
        "The whole chain (detector boxes -> crop -> classifier) on the 600 consumer photos "
        "of the C3PI test split, including the 117 the auto-labeller had rejected."
    ),
}

PIPELINE = (
    "photo -> detector (one box per pill) -> square crop with a 20 % margin -> "
    "classifier (top-5 of 150 C3PI products) -> active ingredients -> interactions"
)

# "Ultralytics YOLO11n model trained on <a path>" -> "YOLO11n". The rest of that string is
# a filesystem path from the training machine and is never returned by the API.
_ARCHITECTURE = re.compile(r"\b(YOLO\S+?)\s+model\b", re.IGNORECASE)


def architecture(onnx_metadata: dict[str, Any]) -> str:
    """The model family from the ONNX description, e.g. "YOLO11n" or "YOLO11s-cls"."""
    found = _ARCHITECTURE.search(str(onnx_metadata.get("description", "")))
    return found.group(1) if found else "unknown"


def metrics_for(run_id: str | None) -> dict[str, float]:
    """The measured scores of that run, or {} when the served file is another version."""
    return dict(MEASURED.get(run_id or "", {}))


def training_for(run_id: str | None) -> dict[str, Any]:
    return dict(TRAINING.get(run_id or "", {}))
