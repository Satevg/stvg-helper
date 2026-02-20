from io import BytesIO
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from detector import (
    CONFIDENCE_THRESHOLD,
    INPUT_SIZE,
    VEHICLE_CLASSES,
    Detection,
    _iou,
    _nms,
    detect_vehicles,
    postprocess,
    preprocess,
)


def _make_jpeg(width: int = 640, height: int = 480, color: tuple[int, int, int] = (128, 128, 128)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (width, height), color=color).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _make_yolo_output(
    boxes: list[tuple[float, float, float, float]],
    class_id: int,
    confidence: float,
    num_anchors: int = 8400,
) -> np.ndarray:
    """Build a synthetic [1, 84, 8400] YOLO output tensor."""
    output = np.zeros((1, 84, num_anchors), dtype=np.float32)
    for i, (cx, cy, w, h) in enumerate(boxes):
        if i >= num_anchors:
            break
        output[0, 0, i] = cx
        output[0, 1, i] = cy
        output[0, 2, i] = w
        output[0, 3, i] = h
        output[0, 4 + class_id, i] = confidence
    return output


# ---------------------------------------------------------------------------
# preprocess
# ---------------------------------------------------------------------------


class TestPreprocess:
    def test_output_shape(self):
        tensor, _ = preprocess(_make_jpeg(640, 480))
        assert tensor.shape == (1, 3, INPUT_SIZE, INPUT_SIZE)

    def test_orig_size_returned(self):
        _, orig = preprocess(_make_jpeg(320, 240))
        assert orig == (320, 240)

    def test_values_in_0_1(self):
        tensor, _ = preprocess(_make_jpeg())
        assert float(tensor.min()) >= 0.0
        assert float(tensor.max()) <= 1.0

    def test_dtype_float32(self):
        tensor, _ = preprocess(_make_jpeg())
        assert tensor.dtype == np.float32

    def test_non_square_input(self):
        tensor, orig = preprocess(_make_jpeg(800, 600))
        assert tensor.shape == (1, 3, INPUT_SIZE, INPUT_SIZE)
        assert orig == (800, 600)


# ---------------------------------------------------------------------------
# _iou
# ---------------------------------------------------------------------------


class TestIou:
    def _box(self, x1: float, y1: float, x2: float, y2: float) -> np.ndarray:
        return np.array([x1, y1, x2, y2], dtype=np.float32)

    def _boxes(self, *args: tuple[float, float, float, float]) -> np.ndarray:
        return np.array(args, dtype=np.float32)

    def test_identical_boxes_iou_is_one(self):
        b = self._box(0, 0, 10, 10)
        result = _iou(b, self._boxes((0, 0, 10, 10)))
        assert pytest.approx(float(result[0]), abs=1e-5) == 1.0

    def test_non_overlapping_boxes_iou_is_zero(self):
        b = self._box(0, 0, 10, 10)
        result = _iou(b, self._boxes((20, 20, 30, 30)))
        assert float(result[0]) == pytest.approx(0.0, abs=1e-5)

    def test_half_overlap(self):
        b = self._box(0, 0, 10, 10)  # area 100
        result = _iou(b, self._boxes((5, 0, 15, 10)))  # overlap 50, union 150
        assert float(result[0]) == pytest.approx(50 / 150, abs=1e-4)

    def test_multiple_boxes(self):
        b = self._box(0, 0, 10, 10)
        result = _iou(b, self._boxes((0, 0, 10, 10), (20, 20, 30, 30)))
        assert result.shape == (2,)
        assert float(result[0]) == pytest.approx(1.0, abs=1e-5)
        assert float(result[1]) == pytest.approx(0.0, abs=1e-5)


# ---------------------------------------------------------------------------
# _nms
# ---------------------------------------------------------------------------


class TestNms:
    def _boxes(self, *args: tuple[float, float, float, float]) -> np.ndarray:
        return np.array(args, dtype=np.float32)

    def _scores(self, *args: float) -> np.ndarray:
        return np.array(args, dtype=np.float32)

    def test_single_box_kept(self):
        kept = _nms(self._boxes((0, 0, 10, 10)), self._scores(0.9))
        assert kept == [0]

    def test_non_overlapping_both_kept(self):
        kept = _nms(self._boxes((0, 0, 10, 10), (50, 50, 60, 60)), self._scores(0.9, 0.8))
        assert set(kept) == {0, 1}

    def test_heavily_overlapping_lower_score_suppressed(self):
        kept = _nms(self._boxes((0, 0, 10, 10), (0, 0, 10, 10)), self._scores(0.9, 0.5))
        assert kept == [0]

    def test_higher_score_wins(self):
        kept = _nms(self._boxes((0, 0, 10, 10), (0, 0, 10, 10)), self._scores(0.5, 0.9))
        assert kept == [1]


# ---------------------------------------------------------------------------
# postprocess
# ---------------------------------------------------------------------------


class TestPostprocess:
    def test_no_detections_for_low_confidence(self):
        output = _make_yolo_output([(320, 240, 100, 80)], class_id=2, confidence=0.10)
        dets = postprocess(output, (640, 480))
        assert dets == []

    def test_car_detected_above_threshold(self):
        output = _make_yolo_output([(320, 240, 100, 80)], class_id=2, confidence=0.90)
        dets = postprocess(output, (640, 480))
        assert len(dets) == 1
        assert dets[0].class_id == 2

    def test_non_vehicle_class_ignored(self):
        # class_id=0 is person — not in VEHICLE_CLASSES
        output = _make_yolo_output([(320, 240, 100, 80)], class_id=0, confidence=0.95)
        dets = postprocess(output, (640, 480))
        assert dets == []

    def test_all_vehicle_classes_detected(self):
        for cls in VEHICLE_CLASSES:
            output = _make_yolo_output([(320, 240, 100, 80)], class_id=cls, confidence=0.90)
            dets = postprocess(output, (640, 480))
            assert len(dets) == 1, f"class_id={cls} not detected"

    def test_bbox_scaled_to_orig_size(self):
        # cx=320, cy=240 in 640x640 space → should map to cx=320*(640/640), cy=240*(480/640) in orig
        output = _make_yolo_output([(320, 240, 64, 48)], class_id=2, confidence=0.90)
        dets = postprocess(output, (640, 480))
        assert len(dets) == 1
        d = dets[0]
        orig_w, orig_h = 640, 480
        scale_x = orig_w / INPUT_SIZE
        scale_y = orig_h / INPUT_SIZE
        assert d.x1 == pytest.approx((320 - 32) * scale_x, abs=1.0)
        assert d.y1 == pytest.approx((240 - 24) * scale_y, abs=1.0)

    def test_confidence_stored(self):
        output = _make_yolo_output([(320, 240, 100, 80)], class_id=2, confidence=0.75)
        dets = postprocess(output, (640, 480))
        assert len(dets) == 1
        assert dets[0].confidence == pytest.approx(0.75, abs=0.01)


# ---------------------------------------------------------------------------
# detect_vehicles
# ---------------------------------------------------------------------------


class TestDetectVehicles:
    def _mock_session(self, output: np.ndarray) -> MagicMock:
        session = MagicMock()
        session.get_inputs.return_value = [MagicMock(name="images")]
        session.run.return_value = [output]
        return session

    def test_no_vehicles_coverage_zero(self):
        output = _make_yolo_output([], class_id=2, confidence=0.0)
        with patch("detector._get_session", return_value=self._mock_session(output)):
            coverage, dets = detect_vehicles(_make_jpeg())
        assert coverage == 0.0
        assert dets == []

    def test_coverage_ratio_computed(self):
        # Box cx=320,cy=240,w=640,h=480 in 640x640 YOLO space, orig=640x480.
        # scale_y=480/640=0.75 → box height in orig = 480*0.75=360, width=640.
        # coverage = (640*360)/(640*480) = 0.75
        output = _make_yolo_output([(320, 240, 640, 480)], class_id=2, confidence=0.90)
        with patch("detector._get_session", return_value=self._mock_session(output)):
            coverage, dets = detect_vehicles(_make_jpeg(640, 480))
        assert coverage == pytest.approx(0.75, abs=0.05)
        assert len(dets) == 1

    def test_coverage_capped_at_one(self):
        # Multiple large overlapping boxes should not exceed 1.0
        boxes = [(320, 240, 640, 480)] * 5
        output = _make_yolo_output(boxes, class_id=2, confidence=0.90)
        with patch("detector._get_session", return_value=self._mock_session(output)):
            coverage, _ = detect_vehicles(_make_jpeg(640, 480))
        assert coverage <= 1.0

    def test_small_vehicle_low_coverage(self):
        # 64x48 box on 640x480 image → coverage ≈ (64*48)/(640*480) ≈ 0.01
        output = _make_yolo_output([(320, 240, 64, 48)], class_id=2, confidence=0.90)
        with patch("detector._get_session", return_value=self._mock_session(output)):
            coverage, dets = detect_vehicles(_make_jpeg(640, 480))
        assert coverage == pytest.approx(3072 / 307200, abs=0.01)
        assert len(dets) == 1
