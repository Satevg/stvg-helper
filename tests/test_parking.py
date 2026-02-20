from io import BytesIO
from unittest.mock import MagicMock, patch

from PIL import Image

from detector import Detection
from parking import (
    Zone,
    _annotate_jpeg,
    _is_free,
    _norm,
    _zone_coverage,
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

    def test_zones_recompute_coverage(self):
        # Detection covers right half of a 300x300 image.
        # Zone is left half (0.0–0.5 x), so zone coverage should be 0.
        jpeg = _make_jpeg(300, 300)
        dets = [_det(150, 0, 300, 300)]
        zones: list[Zone] = [(0.0, 0.0, 0.5, 1.0)]
        with patch("parking.detect_vehicles", return_value=(0.50, dets)):
            free, _ = _is_free(jpeg, zones)
        assert free is True  # no overlap with zone → free

    def test_zones_occupied_when_detection_inside(self):
        # Detection covers full image; zone is full frame → high zone coverage.
        jpeg = _make_jpeg(300, 300)
        dets = [_det(0, 0, 300, 300)]
        zones: list[Zone] = [(0.0, 0.0, 1.0, 1.0)]
        with patch("parking.detect_vehicles", return_value=(1.0, dets)):
            free, _ = _is_free(jpeg, zones)
        assert free is False


# ---------------------------------------------------------------------------
# _zone_coverage
# ---------------------------------------------------------------------------


class TestZoneCoverage:
    def test_no_detections_returns_zero(self):
        zones: list[Zone] = [(0.0, 0.0, 1.0, 1.0)]
        assert _zone_coverage([], zones, 300, 300) == 0.0

    def test_full_frame_zone_full_overlap(self):
        zones: list[Zone] = [(0.0, 0.0, 1.0, 1.0)]
        dets = [_det(0, 0, 300, 300)]
        assert _zone_coverage(dets, zones, 300, 300) == 1.0

    def test_detection_outside_zone_no_coverage(self):
        # Zone is left half; detection is right half.
        zones: list[Zone] = [(0.0, 0.0, 0.5, 1.0)]
        dets = [_det(150, 0, 300, 300)]
        assert _zone_coverage(dets, zones, 300, 300) == 0.0

    def test_partial_overlap(self):
        # Zone is right half (150–300); detection covers full width.
        zones: list[Zone] = [(0.5, 0.0, 1.0, 1.0)]
        dets = [_det(0, 0, 300, 300)]
        # Intersection: x 150–300, y 0–300 = 150×300 = 45000; zone area = 150×300 = 45000
        assert _zone_coverage(dets, zones, 300, 300) == 1.0

    def test_capped_at_one(self):
        # Two overlapping detections covering the same zone area.
        zones: list[Zone] = [(0.0, 0.0, 1.0, 1.0)]
        dets = [_det(0, 0, 300, 300), _det(0, 0, 300, 300)]
        assert _zone_coverage(dets, zones, 300, 300) == 1.0

    def test_empty_zones_returns_zero(self):
        dets = [_det(0, 0, 100, 100)]
        assert _zone_coverage(dets, [], 300, 300) == 0.0

    def test_multiple_zones(self):
        # Two non-overlapping zones each covering a quarter of the 300x300 image.
        # Detection covers the top-left quarter only.
        zones: list[Zone] = [(0.0, 0.0, 0.5, 0.5), (0.5, 0.5, 1.0, 1.0)]
        dets = [_det(0, 0, 150, 150)]
        total_zone_area = 150 * 150 + 150 * 150  # 45000
        covered = 150 * 150  # 22500
        expected = covered / total_zone_area  # 0.5
        assert abs(_zone_coverage(dets, zones, 300, 300) - expected) < 1e-6


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

    def test_with_zones_returns_valid_jpeg(self):
        zones: list[Zone] = [(0.0, 0.5, 1.0, 1.0)]
        result = _annotate_jpeg(_make_jpeg(300, 300), [], zones)
        assert Image.open(BytesIO(result)).format == "JPEG"

    def test_with_zones_dimensions_unchanged(self):
        zones: list[Zone] = [(0.0, 0.5, 1.0, 1.0)]
        result = _annotate_jpeg(_make_jpeg(600, 400), [_det(10, 10, 50, 50)], zones)
        assert Image.open(BytesIO(result)).size == (600, 400)

    def test_cell_outside_zone_not_highlighted(self):
        # Zone covers only the bottom half; top-left cell should NOT be green.
        jpeg = _make_jpeg(300, 300, color=(100, 0, 0))
        zones: list[Zone] = [(0.0, 0.5, 1.0, 1.0)]
        result = _annotate_jpeg(jpeg, [], zones)
        img = Image.open(BytesIO(result)).convert("RGB")
        r, g, b = img.getpixel((1, 1))  # top-left cell centre
        assert r >= g, f"cell outside zone should not be green, got R={r} G={g} B={b}"

    def test_cell_inside_zone_highlighted_when_free(self):
        # Zone covers full frame; no detections → bottom-right area should be green.
        jpeg = _make_jpeg(300, 300, color=(100, 0, 0))
        zones: list[Zone] = [(0.0, 0.0, 1.0, 1.0)]
        result = _annotate_jpeg(jpeg, [], zones)
        img = Image.open(BytesIO(result)).convert("RGB")
        r, g, b = img.getpixel((1, 1))
        assert g > r, f"expected G > R in free zone cell, got R={r} G={g} B={b}"
