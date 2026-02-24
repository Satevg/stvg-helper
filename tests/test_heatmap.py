from unittest.mock import MagicMock, patch
import time
from heatmap import Slot, update_heatmap, get_confirmed_slots, PROXIMITY_THRESHOLD, CONFIRMATION_THRESHOLD
from detector import Detection

def _det(x1, y1, x2, y2):
    return Detection(x1=x1, y1=y1, x2=x2, y2=y2, confidence=0.9, class_id=2)

@patch("heatmap._get_table")
def test_update_heatmap_new_slot(mock_get_table):
    table = MagicMock()
    mock_get_table.return_value = table
    table.get_item.return_value = {"Item": {"slots": []}}
    
    dets = [_det(0.1, 0.1, 0.2, 0.2)]
    update_heatmap("Build", 1, dets)
    
    # Verify put_item was called with one slot
    args, kwargs = table.put_item.call_args
    slots = kwargs["Item"]["slots"]
    assert len(slots) == 1
    assert slots[0]["count"] == 1

@patch("heatmap._get_table")
def test_update_heatmap_existing_slot(mock_get_table):
    table = MagicMock()
    mock_get_table.return_value = table
    # Existing slot at center (0.15, 0.15)
    existing_slot = {
        "x1": 0.1, "y1": 0.1, "x2": 0.2, "y2": 0.2,
        "count": 1, "last_seen": time.time()
    }
    table.get_item.return_value = {"Item": {"slots": [existing_slot]}}
    
    # New detection very close to existing slot
    dets = [_det(0.11, 0.11, 0.21, 0.21)]
    update_heatmap("Build", 1, dets)
    
    args, kwargs = table.put_item.call_args
    slots = kwargs["Item"]["slots"]
    assert len(slots) == 1
    assert slots[0]["count"] == 2

@patch("heatmap._get_table")
def test_get_confirmed_slots(mock_get_table):
    table = MagicMock()
    mock_get_table.return_value = table
    slots_data = [
        {"x1": 0, "y1": 0, "x2": 0.1, "y2": 0.1, "count": CONFIRMATION_THRESHOLD, "last_seen": time.time()},
        {"x1": 0.5, "y1": 0.5, "x2": 0.6, "y2": 0.6, "count": 1, "last_seen": time.time()}
    ]
    table.get_item.return_value = {"Item": {"slots": slots_data}}
    
    confirmed = get_confirmed_slots("Build", 1)
    assert len(confirmed) == 1
    assert confirmed[0].count == CONFIRMATION_THRESHOLD

def test_slot_distance():
    s = Slot(x1=0, y1=0, x2=0.2, y2=0.2, count=1, last_seen=0)
    d = _det(0, 0, 0.2, 0.2)
    assert s.distance_to(d) == 0
    
    d2 = _det(0.5, 0.5, 0.7, 0.7)
    # distance between (0.1, 0.1) and (0.6, 0.6)
    # sqrt(0.5^2 + 0.5^2) = sqrt(0.5) approx 0.707
    assert abs(s.distance_to(d2) - 0.707106) < 0.001
