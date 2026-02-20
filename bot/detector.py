import logging
import os
from functools import lru_cache
from io import BytesIO
from typing import Any, NamedTuple

import numpy as np
import numpy.typing as npt
from PIL import Image

logger = logging.getLogger(__name__)

# COCO class IDs for vehicles: car, motorcycle, bus, truck
VEHICLE_CLASSES: frozenset[int] = frozenset({2, 3, 5, 7})

CONFIDENCE_THRESHOLD = 0.35
IOU_THRESHOLD = 0.45
INPUT_SIZE = 640

_MODEL_PATH = os.environ.get(
    "YOLO_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "models", "yolov8n.onnx"),
)


class Detection(NamedTuple):
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float
    class_id: int


@lru_cache(maxsize=1)
def _get_session() -> Any:
    import onnxruntime as ort

    logger.info("Loading ONNX model from %s", _MODEL_PATH)
    return ort.InferenceSession(_MODEL_PATH, providers=["CPUExecutionProvider"])


def preprocess(jpeg_bytes: bytes) -> tuple[npt.NDArray[np.float32], tuple[int, int]]:
    """Resize to INPUT_SIZExINPUT_SIZE, normalize to [0,1], return (tensor [1,3,H,W], orig_size)."""
    img = Image.open(BytesIO(jpeg_bytes)).convert("RGB")
    orig_size = img.size  # (width, height)
    img_resized = img.resize((INPUT_SIZE, INPUT_SIZE), Image.Resampling.BILINEAR)
    arr = np.array(img_resized, dtype=np.float32) / 255.0
    arr = arr.transpose(2, 0, 1)  # HWC → CHW
    arr = np.expand_dims(arr, 0)  # [1, 3, H, W]
    return arr, orig_size


def _iou(box: npt.NDArray[np.float32], boxes: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    """IoU between one box and an array of boxes (x1y1x2y2 format)."""
    ix1 = np.maximum(box[0], boxes[:, 0])
    iy1 = np.maximum(box[1], boxes[:, 1])
    ix2 = np.minimum(box[2], boxes[:, 2])
    iy2 = np.minimum(box[3], boxes[:, 3])
    inter = np.maximum(0.0, ix2 - ix1) * np.maximum(0.0, iy2 - iy1)
    area_box = (box[2] - box[0]) * (box[3] - box[1])
    area_boxes = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    union = area_box + area_boxes - inter
    result: npt.NDArray[np.float32] = inter / np.maximum(union, 1e-6)
    return result


def _nms(boxes: npt.NDArray[np.float32], scores: npt.NDArray[np.float32]) -> list[int]:
    """Non-maximum suppression; returns indices of kept detections."""
    order = scores.argsort()[::-1]
    kept: list[int] = []
    while len(order) > 0:
        i = order[0]
        kept.append(int(i))
        if len(order) == 1:
            break
        iou = _iou(boxes[i], boxes[order[1:]])
        order = order[1:][iou < IOU_THRESHOLD]
    return kept


def postprocess(
    output: npt.NDArray[np.float32],
    orig_size: tuple[int, int],
) -> list[Detection]:
    """Parse YOLOv8 output [1, 84, 8400] into Detection list (vehicle classes only)."""
    preds = output[0].T  # [8400, 84]
    cx, cy, w, h = preds[:, 0], preds[:, 1], preds[:, 2], preds[:, 3]
    class_scores = preds[:, 4:]  # [8400, 80]
    class_ids = class_scores.argmax(axis=1)
    confidences = class_scores.max(axis=1)

    orig_w, orig_h = orig_size
    scale_x = orig_w / INPUT_SIZE
    scale_y = orig_h / INPUT_SIZE

    x1 = (cx - w / 2) * scale_x
    y1 = (cy - h / 2) * scale_y
    x2 = (cx + w / 2) * scale_x
    y2 = (cy + h / 2) * scale_y

    vehicle_mask = np.array([int(cid) in VEHICLE_CLASSES for cid in class_ids])
    conf_mask = confidences >= CONFIDENCE_THRESHOLD
    mask = vehicle_mask & conf_mask

    if not mask.any():
        return []

    fboxes = np.stack([x1[mask], y1[mask], x2[mask], y2[mask]], axis=1).astype(np.float32)
    fscores = confidences[mask].astype(np.float32)
    fclass_ids = class_ids[mask]

    kept = _nms(fboxes, fscores)
    return [
        Detection(
            x1=float(fboxes[i, 0]),
            y1=float(fboxes[i, 1]),
            x2=float(fboxes[i, 2]),
            y2=float(fboxes[i, 3]),
            confidence=float(fscores[i]),
            class_id=int(fclass_ids[i]),
        )
        for i in kept
    ]


def detect_vehicles(jpeg_bytes: bytes) -> tuple[float, list[Detection]]:
    """Run vehicle detection on JPEG bytes. Returns (coverage_ratio, detections).

    coverage_ratio = total bounding-box area / image area (capped at 1.0).
    """
    session = _get_session()
    tensor, orig_size = preprocess(jpeg_bytes)
    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: tensor})
    detections = postprocess(outputs[0], orig_size)

    orig_w, orig_h = orig_size
    img_area = orig_w * orig_h
    if img_area == 0 or not detections:
        return 0.0, detections

    covered = sum((d.x2 - d.x1) * (d.y2 - d.y1) for d in detections)
    coverage = min(covered / img_area, 1.0)
    return coverage, detections
