from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

from anthropic.types import TextBlock
from PIL import Image

from parking import (
    _CELL_RE,
    _GRID_CELLS,
    _annotate_jpeg,
    _is_free,
    _norm,
    find_camera,
)


def _make_jpeg(width: int = 300, height: int = 300, color: tuple[int, int, int] = (100, 100, 100)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (width, height), color=color).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


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
        # A bare dot should collapse to a single space
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
        cameras = [{"name": "stream1"}]  # no "title" key
        assert find_camera(cameras, "Авиационная 8", 1) is None


# ---------------------------------------------------------------------------
# _CELL_RE
# ---------------------------------------------------------------------------


class TestCellRe:
    def test_all_nine_cells_match(self):
        for cell in _GRID_CELLS:
            m = _CELL_RE.match(f"yes {cell}")
            assert m is not None, f"no match for cell '{cell}'"
            assert m.group(1).lower() == cell

    def test_case_insensitive(self):
        assert _CELL_RE.match("yes Middle-Center") is not None
        assert _CELL_RE.match("YES TOP-LEFT") is not None

    def test_no_response_does_not_match(self):
        assert _CELL_RE.match("no") is None

    def test_yes_without_cell_does_not_match(self):
        assert _CELL_RE.match("yes") is None

    def test_captures_cell_name(self):
        m = _CELL_RE.match("yes bottom-right")
        assert m is not None
        assert m.group(1).lower() == "bottom-right"


# ---------------------------------------------------------------------------
# _annotate_jpeg
# ---------------------------------------------------------------------------


class TestAnnotateJpeg:
    def test_returns_valid_jpeg(self):
        result = _annotate_jpeg(_make_jpeg(), "top-left")
        img = Image.open(BytesIO(result))
        assert img.format == "JPEG"

    def test_dimensions_unchanged(self):
        result = _annotate_jpeg(_make_jpeg(400, 200), "middle-center")
        assert Image.open(BytesIO(result)).size == (400, 200)

    def test_all_cells_produce_output(self):
        jpeg = _make_jpeg()
        for cell in _GRID_CELLS:
            assert len(_annotate_jpeg(jpeg, cell)) > 0

    def test_output_differs_from_input(self):
        jpeg = _make_jpeg()
        assert _annotate_jpeg(jpeg, "top-left") != jpeg

    def test_outline_region_has_green_tint(self):
        # Use a red image so the green overlay stands out clearly.
        jpeg = _make_jpeg(300, 300, color=(200, 0, 0))
        result = _annotate_jpeg(jpeg, "top-left")
        img = Image.open(BytesIO(result)).convert("RGB")
        # Pixel (1, 1) falls on the top-left outline (fully opaque green).
        r, g, b = img.getpixel((1, 1))
        assert g > r, f"expected G > R at outline pixel, got R={r} G={g} B={b}"
        assert g > b, f"expected G > B at outline pixel, got R={r} G={g} B={b}"


# ---------------------------------------------------------------------------
# _is_free
# ---------------------------------------------------------------------------


def _mock_client(text: str) -> MagicMock:
    response = MagicMock()
    response.content = [TextBlock(type="text", text=text)]
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    return client


def _mock_client_bad_content() -> MagicMock:
    response = MagicMock()
    response.content = [MagicMock()]  # not a TextBlock
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=response)
    return client


class TestIsFree:
    async def test_yes_with_cell(self):
        free, cell = await _is_free(_mock_client("yes top-right"), b"img")
        assert free is True
        assert cell == "top-right"

    async def test_yes_cell_case_insensitive(self):
        free, cell = await _is_free(_mock_client("yes Middle-Center"), b"img")
        assert free is True
        assert cell == "middle-center"

    async def test_yes_without_cell(self):
        free, cell = await _is_free(_mock_client("yes"), b"img")
        assert free is True
        assert cell is None

    async def test_no(self):
        free, cell = await _is_free(_mock_client("no"), b"img")
        assert free is False
        assert cell is None

    async def test_unexpected_content_type_returns_false(self):
        free, cell = await _is_free(_mock_client_bad_content(), b"img")
        assert free is False
        assert cell is None

    async def test_all_cells_parsed(self):
        for cell in _GRID_CELLS:
            free, parsed = await _is_free(_mock_client(f"yes {cell}"), b"img")
            assert free is True
            assert parsed == cell
