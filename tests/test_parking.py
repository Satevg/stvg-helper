from io import BytesIO
from unittest.mock import MagicMock, patch

from PIL import Image

from detector import Detection
from parking import (
    _annotate_jpeg,
    _is_free,
    _norm,
    find_camera,
)


def _make_jpeg(width: int = 300, height: int = 300, color: tuple[int, int, int] = (100, 100, 100)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (width, height), color=color).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _det(x1: float, y1: float, x2: float, y2: float) -> Detection:
    return Detection(x1=x1, y1=y1, x2=x2, y2=y2, confidence=0.9, class_id=2)


# ---------------------------------------------------------------------------
# _norm
# ---------------------------------------------------------------------------


class TestNorm:
    def test_lowercase(self):
        assert _norm("Авиационная 8") == "авиационная 8"

    def test_collapses_dot_then_space(self):
        assert _norm("Б.Райт 1") == _norm("Б. Райт 1")

    def test_collapses_multiple_spaces(self):
        assert _norm("a  b") == "a b"

    def test_strips_leading_trailing_whitespace(self):
        assert _norm("  foo  ") == "foo"

    def test_dot_becomes_space(self):
        assert _norm("a.b") == "a b"


# ---------------------------------------------------------------------------
# find_camera
# ---------------------------------------------------------------------------


class TestFindCamera:
    def _cam(self, title: str, name: str = "stream1") -> dict:
        return {"title": title, "name": name}

    def test_exact_title_match(self):
        cameras = [self._cam("Авиационная 8 — Камера 01")]
        assert find_camera(cameras, "Авиационная 8", 1) is not None

    def test_dot_variant_normalised(self):
        cameras = [self._cam("Б. Райт 1 — Камера 02")]
        assert find_camera(cameras, "Б.Райт 1", 2) is not None
        assert find_camera(cameras, "Б. Райт 1", 2) is not None

    def test_camera_number_zero_padded(self):
        cameras = [self._cam("Яковлева 1 — Камера 07")]
        assert find_camera(cameras, "Яковлева 1", 7) is not None

    def test_wrong_camera_number_returns_none(self):
        cameras = [self._cam("Авиационная 8 — Камера 01")]
        assert find_camera(cameras, "Авиационная 8", 2) is None

    def test_wrong_building_returns_none(self):
        cameras = [self._cam("Авиационная 8 — Камера 01")]
        assert find_camera(cameras, "Авиационная 10", 1) is None

    def test_empty_list_returns_none(self):
        assert find_camera([], "Авиационная 8", 1) is None

    def test_returns_correct_camera_from_multiple(self):
        cam1 = self._cam("Авиационная 8 — Камера 01", name="stream1")
        cam2 = self._cam("Авиационная 8 — Камера 02", name="stream2")
        result = find_camera([cam1, cam2], "Авиационная 8", 2)
        assert result is not None
        assert result["name"] == "stream2"

    def test_missing_title_field_skipped(self):
        cameras = [{"name": "stream1"}]
        assert find_camera(cameras, "Авиационная 8", 1) is None


# ---------------------------------------------------------------------------
# _is_free
# ---------------------------------------------------------------------------


class TestIsFree:
    def test_low_coverage_is_free(self):
        with patch("parking.detect_vehicles", return_value=(0.10, [])):
            free, detections = _is_free(b"img")
        assert free is True
        assert detections == []

    def test_high_coverage_is_not_free(self):
        dets = [_det(0, 0, 100, 100)]
        with patch("parking.detect_vehicles", return_value=(0.80, dets)):
            free, detections = _is_free(b"img")
        assert free is False
        assert detections == dets

    def test_exactly_at_threshold_is_not_free(self):
        with patch("parking.detect_vehicles", return_value=(0.40, [])):
            free, _ = _is_free(b"img")
        assert free is False

    def test_just_below_threshold_is_free(self):
        with patch("parking.detect_vehicles", return_value=(0.399, [])):
            free, _ = _is_free(b"img")
        assert free is True

    def test_returns_detections(self):
        dets = [_det(10, 20, 50, 60), _det(100, 100, 200, 200)]
        with patch("parking.detect_vehicles", return_value=(0.05, dets)):
            free, detections = _is_free(b"img")
        assert free is True
        assert detections == dets


# ---------------------------------------------------------------------------
# _annotate_jpeg
# ---------------------------------------------------------------------------


class TestAnnotateJpeg:
    def test_returns_valid_jpeg(self):
        result = _annotate_jpeg(_make_jpeg(), [])
        assert Image.open(BytesIO(result)).format == "JPEG"

    def test_dimensions_unchanged(self):
        result = _annotate_jpeg(_make_jpeg(600, 400), [_det(10, 10, 50, 50)])
        assert Image.open(BytesIO(result)).size == (600, 400)

    def test_no_detections_all_cells_green(self):
        # With no vehicles every cell should be highlighted green
        jpeg = _make_jpeg(300, 300, color=(100, 0, 0))
        result = _annotate_jpeg(jpeg, [])
        img = Image.open(BytesIO(result)).convert("RGB")
        # Centre of top-left cell should have a green tint from the overlay
        r, g, b = img.getpixel((1, 1))
        assert g > r, f"expected G > R in free cell, got R={r} G={g} B={b}"

    def test_occupied_cell_not_highlighted(self):
        # A detection covering the entire image — no cell should be green
        jpeg = _make_jpeg(300, 300, color=(100, 0, 0))
        result = _annotate_jpeg(jpeg, [_det(0, 0, 300, 300)])
        img = Image.open(BytesIO(result)).convert("RGB")
        r, g, b = img.getpixel((1, 1))
        assert r >= g, f"expected occupied cell not green, got R={r} G={g} B={b}"

    def test_multiple_detections(self):
        dets = [_det(0, 0, 50, 50), _det(100, 100, 200, 200)]
        result = _annotate_jpeg(_make_jpeg(), dets)
        assert Image.open(BytesIO(result)).format == "JPEG"
