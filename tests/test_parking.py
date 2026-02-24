import time
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from detector import Detection
from parking import (
    _annotate_jpeg,
    _check_camera,
    _is_free,
    _norm,
    fetch_cameras_cached,
    find_camera,
)


def _make_jpeg(width: int = 300, height: int = 300, color: tuple[int, int, int] = (100, 100, 100)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (width, height), color=color).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def _det(x1: float, y1: float, x2: float, y2: float) -> Detection:
    return Detection(x1=x1, y1=y1, x2=x2, y2=y2, confidence=0.9, class_id=2)


@patch("parking.update_heatmap")
class TestIsFree:
    def test_no_slots_is_not_free(self, mock_update):
        with patch("parking.get_confirmed_slots", return_value=[]):
            with patch("parking.detect_vehicles", return_value=(0.0, [])):
                free, detections, slots = _is_free(b"img", "Build", 1)
        assert free is False
        assert slots == []
        mock_update.assert_called_once()

    def test_occupied_slot_is_not_free(self, mock_update):
        slot = MagicMock(x1=0, y1=0, x2=100, y2=100)
        dets = [_det(10, 10, 50, 50)]
        with patch("parking.get_confirmed_slots", return_value=[slot]):
            with patch("parking.detect_vehicles", return_value=(0.1, dets)):
                free, detections, slots = _is_free(b"img", "Build", 1)
        assert free is False
        assert slots == []

    def test_unoccupied_slot_is_free(self, mock_update):
        slot = MagicMock(x1=200, y1=200, x2=300, y2=300)
        dets = [_det(0, 0, 100, 100)]
        with patch("parking.get_confirmed_slots", return_value=[slot]):
            with patch("parking.detect_vehicles", return_value=(0.1, dets)):
                free, detections, slots = _is_free(b"img", "Build", 1)
        assert free is True
        assert slots == [slot]


class TestAnnotateJpeg:
    def test_returns_valid_jpeg(self):
        result = _annotate_jpeg(_make_jpeg(), [], [])
        assert Image.open(BytesIO(result)).format == "JPEG"

    def test_dimensions_unchanged(self):
        result = _annotate_jpeg(_make_jpeg(600, 400), [_det(10, 10, 50, 50)], [])
        assert Image.open(BytesIO(result)).size == (600, 400)

    def test_free_slot_highlighted(self):
        slot = MagicMock(x1=0, y1=0, x2=100, y2=100)
        jpeg = _make_jpeg(300, 300, color=(100, 0, 0))
        result = _annotate_jpeg(jpeg, [], [slot])
        img = Image.open(BytesIO(result)).convert("RGB")
        r, g, b = img.getpixel((1, 1))
        assert g > r, f"expected G > R in free slot, got R={r} G={g} B={b}"


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


class TestFindCamera:
    def _cam(self, title: str, name: str = "stream1") -> dict:
        return {"title": title, "name": name}

    def test_exact_title_match(self):
        cameras = [self._cam("Авиационная 8 — Камера 01")]
        assert find_camera(cameras, "Авиационная 8", 1) is not None

    def test_returns_correct_camera_from_multiple(self):
        cam1 = self._cam("Авиационная 8 — Камера 01", name="stream1")
        cam2 = self._cam("Авиационная 8 — Камера 02", name="stream2")
        result = find_camera([cam1, cam2], "Авиационная 8", 2)
        assert result is not None
        assert result["name"] == "stream2"


class TestFetchCamerasCached:
    @patch("parking.fetch_cameras")
    def test_cache_miss_calls_fetch(self, mock_fetch):
        import parking

        # Reset cache state
        parking._cameras_cache = None
        parking._cameras_cache_ts = 0.0
        parking._cameras_index = {}

        mock_fetch.return_value = [{"title": "Test", "name": "cam1"}]
        result = fetch_cameras_cached()
        assert result == [{"title": "Test", "name": "cam1"}]
        mock_fetch.assert_called_once()

    @patch("parking.fetch_cameras")
    def test_cache_hit_skips_fetch(self, mock_fetch):
        import parking

        # Pre-populate cache
        cached = [{"title": "Cached", "name": "cam1"}]
        parking._cameras_cache = cached
        parking._cameras_cache_ts = time.monotonic()
        parking._cameras_index = {}

        result = fetch_cameras_cached()
        assert result == cached
        mock_fetch.assert_not_called()

    @patch("parking.fetch_cameras")
    def test_cache_expired_refetches(self, mock_fetch):
        import parking

        parking._cameras_cache = [{"title": "Old"}]
        parking._cameras_cache_ts = time.monotonic() - 600  # 10 min ago
        parking._cameras_index = {}

        mock_fetch.return_value = [{"title": "New"}]
        result = fetch_cameras_cached()
        assert result == [{"title": "New"}]
        mock_fetch.assert_called_once()


class TestCheckCamera:
    @pytest.mark.asyncio
    @patch("parking._is_free")
    @patch("parking._fetch_jpeg")
    async def test_returns_free_spot(self, mock_fetch_jpeg, mock_is_free):
        mock_fetch_jpeg.return_value = b"jpeg_bytes"
        slot = MagicMock()
        mock_is_free.return_value = (True, [_det(0.1, 0.1, 0.2, 0.2)], [slot])

        cam = {"name": "cam1", "streamer_hostname": "srv", "playback_config": {"token": "t"}}
        free, jpeg, detections, free_slots = await _check_camera(cam, "Build", 1)

        assert free is True
        assert jpeg == b"jpeg_bytes"
        assert len(free_slots) == 1

    @pytest.mark.asyncio
    @patch("parking._fetch_jpeg")
    async def test_returns_false_on_no_jpeg(self, mock_fetch_jpeg):
        mock_fetch_jpeg.return_value = None

        cam = {"name": "cam1", "streamer_hostname": "srv", "playback_config": {"token": "t"}}
        free, jpeg, detections, free_slots = await _check_camera(cam, "Build", 1)

        assert free is False
        assert jpeg is None
