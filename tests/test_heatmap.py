import time
from unittest.mock import MagicMock, patch

from parking.detector import Detection
from parking.heatmap import (
    ALPHA_FLOOR,
    CONFIRMATION_THRESHOLD,
    MERGE_IOU_THRESHOLD,
    PROXIMITY_THRESHOLD,
    Slot,
    _box_iou,
    get_confirmed_slots,
    update_heatmap,
)


def _det(x1, y1, x2, y2):
    return Detection(x1=x1, y1=y1, x2=x2, y2=y2, confidence=0.9, class_id=2)


@patch("parking.heatmap._get_table")
def test_update_heatmap_new_slot(mock_get_table):
    table = MagicMock()
    mock_get_table.return_value = table
    table.get_item.return_value = {"Item": {"slots": []}}

    # Box must be > MIN_DETECTION_AREA (0.02): 0.15*0.15 = 0.0225
    dets = [_det(0.1, 0.1, 0.25, 0.25)]
    update_heatmap("Build", 1, dets)

    # Verify put_item was called with one slot
    args, kwargs = table.put_item.call_args
    slots = kwargs["Item"]["slots"]
    assert len(slots) == 1
    assert slots[0]["count"] == 1


@patch("parking.heatmap._get_table")
def test_update_heatmap_existing_slot(mock_get_table):
    table = MagicMock()
    mock_get_table.return_value = table
    # Existing slot at center (0.175, 0.175), area=0.0225
    existing_slot = {"x1": 0.1, "y1": 0.1, "x2": 0.25, "y2": 0.25, "count": 1, "last_seen": time.time()}
    table.get_item.return_value = {"Item": {"slots": [existing_slot]}}

    # Detection close to existing slot (area=0.0225 > MIN_DETECTION_AREA), high IoU
    dets = [_det(0.11, 0.11, 0.26, 0.26)]
    update_heatmap("Build", 1, dets)

    args, kwargs = table.put_item.call_args
    slots = kwargs["Item"]["slots"]
    assert len(slots) == 1
    assert slots[0]["count"] == 2


@patch("parking.heatmap._get_table")
def test_get_confirmed_slots(mock_get_table):
    table = MagicMock()
    mock_get_table.return_value = table
    slots_data = [
        {"x1": 0, "y1": 0, "x2": 0.1, "y2": 0.1, "count": CONFIRMATION_THRESHOLD, "last_seen": time.time()},
        {"x1": 0.5, "y1": 0.5, "x2": 0.6, "y2": 0.6, "count": 1, "last_seen": time.time()},
    ]
    table.get_item.return_value = {"Item": {"slots": slots_data}}

    confirmed = get_confirmed_slots("Build", 1)
    assert len(confirmed) == 1
    assert confirmed[0].count == CONFIRMATION_THRESHOLD


def test_confirmation_threshold_is_ten():
    assert CONFIRMATION_THRESHOLD == 10


def test_slot_distance():
    s = Slot(x1=0, y1=0, x2=0.2, y2=0.2, count=1, last_seen=0)
    d = _det(0, 0, 0.2, 0.2)
    assert s.distance_to(d) == 0

    d2 = _det(0.5, 0.5, 0.7, 0.7)
    # distance between (0.1, 0.1) and (0.6, 0.6)
    # sqrt(0.5^2 + 0.5^2) = sqrt(0.5) approx 0.707
    assert abs(s.distance_to(d2) - 0.707106) < 0.001


class TestBoxIou:
    def test_identical_boxes(self):
        assert _box_iou(0, 0, 1, 1, 0, 0, 1, 1) == 1.0

    def test_no_overlap(self):
        assert _box_iou(0, 0, 0.1, 0.1, 0.5, 0.5, 0.6, 0.6) == 0.0

    def test_partial_overlap(self):
        iou = _box_iou(0, 0, 0.2, 0.2, 0.1, 0.1, 0.3, 0.3)
        # Intersection: 0.1*0.1 = 0.01, Union: 2*0.04 - 0.01 = 0.07
        assert abs(iou - 0.01 / 0.07) < 0.001

    def test_zero_area_box(self):
        assert _box_iou(0, 0, 0, 0, 0, 0, 1, 1) == 0.0

    def test_slot_iou_method(self):
        s = Slot(x1=0, y1=0, x2=0.2, y2=0.2, count=1, last_seen=0)
        d = _det(0, 0, 0.2, 0.2)
        assert s.iou(d) == 1.0


@patch("parking.heatmap._get_table")
def test_alpha_floor_prevents_freezing(mock_get_table):
    """After many observations, alpha should not drop below ALPHA_FLOOR."""
    table = MagicMock()
    mock_get_table.return_value = table
    # Existing slot seen 1000 times — without floor, alpha would be ~0.001
    # Box area=0.0225 > MIN_DETECTION_AREA so the detection passes the size filter
    existing_slot = {"x1": 0.1, "y1": 0.1, "x2": 0.25, "y2": 0.25, "count": 1000, "last_seen": time.time()}
    table.get_item.return_value = {"Item": {"slots": [existing_slot]}}

    # Slightly shifted detection (close enough to merge, with good IoU, area > MIN_DETECTION_AREA)
    dets = [_det(0.11, 0.11, 0.26, 0.26)]
    update_heatmap("Build", 1, dets)

    args, kwargs = table.put_item.call_args
    slot = kwargs["Item"]["slots"][0]
    # With ALPHA_FLOOR=0.02, the slot should shift more than 1/1001 would allow
    # New x1 = (1-0.02)*0.1 + 0.02*0.11 = 0.098 + 0.0022 = 0.1002
    assert float(slot["x1"]) > 0.1001, f"Expected drift > 0.1001, got {float(slot['x1'])}"


@patch("parking.heatmap._get_table")
def test_iou_gated_merge_rejection(mock_get_table):
    """Detections with nearby centers but low IoU should NOT merge."""
    table = MagicMock()
    mock_get_table.return_value = table
    # Small slot: 0.1x0.1 box centered at (0.15, 0.15)
    existing_slot = {"x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.2, "count": 5, "last_seen": time.time()}
    table.get_item.return_value = {"Item": {"slots": [existing_slot]}}

    # Detection with nearby center but MUCH larger box — low IoU
    dets = [_det(0.0, 0.0, 0.5, 0.5)]
    update_heatmap("Build", 1, dets)

    args, kwargs = table.put_item.call_args
    slots = kwargs["Item"]["slots"]
    # Should create a new slot instead of merging; original slot decays by COUNT_DECAY (5→4)
    assert len(slots) == 2, f"Expected 2 slots (rejected merge), got {len(slots)}"
    counts = sorted([s["count"] for s in slots])
    assert counts == [1, 4]


@patch("parking.heatmap._get_table")
def test_ttl_field_set_on_put(mock_get_table):
    """put_item should include a ttl field for DynamoDB TTL safety net."""
    table = MagicMock()
    mock_get_table.return_value = table
    table.get_item.return_value = {"Item": {"slots": []}}

    update_heatmap("Build", 1, [_det(0.1, 0.1, 0.2, 0.2)])

    args, kwargs = table.put_item.call_args
    item = kwargs["Item"]
    assert "ttl" in item
    # TTL should be ~14 days from now
    assert item["ttl"] > time.time() + 13 * 86400
