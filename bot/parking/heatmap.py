import os
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from parking.detector import Detection

logger = Logger(child=True)

# DynamoDB table name for storing user data and parking clusters
TABLE_NAME = os.environ.get("DYNAMODB_TABLE", "stvg-helper")

# Distance threshold (normalized 0.0-1.0) to consider two detections as the same spot.
# 0.05 is approximately 5% of the frame width/height.
PROXIMITY_THRESHOLD = 0.05

# Minimum number of times a vehicle must be seen in a spot to "confirm" it as a real slot.
# This filters out temporary stops, moving cars, or transient delivery vehicles.
CONFIRMATION_THRESHOLD = 10

# Floor for the moving average alpha — new data always has at least this much influence.
# Prevents slots from "freezing" after many observations.
ALPHA_FLOOR = 0.02

# Minimum IoU overlap required (in addition to center distance) to merge a detection into a slot.
# Prevents merging differently-sized vehicles that happen to have nearby centers.
MERGE_IOU_THRESHOLD = 0.3

# Minimum IoU overlap required to consider a confirmed slot as currently occupied.
# Filters out vehicles driving past that only clip the edge of a slot's bounding box.
OCCUPIED_IOU_THRESHOLD = 0.2

# Minimum bounding box area (normalized) to be considered a valid parking detection.
# Filters out tiny far-away vehicles (e.g. cars across the street). 0.02 = 2% of frame area.
MIN_DETECTION_AREA = 0.02

# Maximum count a slot can reach. Prevents unbounded growth and keeps the moving
# average responsive. At COUNT_CAP the alpha floor still applies.
COUNT_CAP = 30

# How much to decrease a slot's count each scan where it had no matching detection.
# A confirmed slot (count=5) missed ~25 times in a row drops back to 0 and gets pruned.
COUNT_DECAY = 1


@dataclass
class Slot:
    """Represents a learned parking spot (cluster of detections)."""

    x1: float
    y1: float
    x2: float
    y2: float
    count: int  # Number of times a vehicle was seen here
    last_seen: float  # Timestamp of the most recent detection

    def distance_to(self, d: Detection) -> float:
        """Calculate Euclidean distance between the center of this slot and a new detection."""
        cx1, cy1 = (self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0
        cx2, cy2 = (d.x1 + d.x2) / 2.0, (d.y1 + d.y2) / 2.0
        dist: float = ((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2) ** 0.5
        return dist

    def iou(self, d: Detection) -> float:
        """Calculate IoU (Intersection over Union) between this slot and a detection."""
        return _box_iou(self.x1, self.y1, self.x2, self.y2, d.x1, d.y1, d.x2, d.y2)


def _box_iou(ax1: float, ay1: float, ax2: float, ay2: float, bx1: float, by1: float, bx2: float, by2: float) -> float:
    """Calculate IoU between two axis-aligned bounding boxes."""
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    union = area_a + area_b - inter
    if union <= 0:
        return 0.0
    return inter / union


def _get_table() -> Any:
    """Initialize the DynamoDB table resource."""
    return boto3.resource("dynamodb").Table(TABLE_NAME)


def get_confirmed_slots(building: str, cam_num: int) -> list[Slot]:
    """Retrieve slots that have reached the CONFIRMATION_THRESHOLD from DynamoDB."""
    table = _get_table()
    try:
        # Fetch the entire slot list for a specific camera
        response = table.get_item(Key={"PK": f"CAM#{building}", "SK": f"SLOTS#{cam_num}"})
        if "Item" not in response:
            return []

        slots_data = response["Item"].get("slots", [])
        slots = [
            Slot(
                x1=float(s["x1"]),
                y1=float(s["y1"]),
                x2=float(s["x2"]),
                y2=float(s["y2"]),
                count=int(s["count"]),
                last_seen=float(s["last_seen"]),
            )
            for s in slots_data
        ]
        # Only return slots that are "trusted" (seen enough times)
        return [s for s in slots if s.count >= CONFIRMATION_THRESHOLD]
    except Exception:
        logger.exception("Failed to get slots from DynamoDB")
        return []


def update_heatmap(building: str, cam_num: int, detections: list[Detection]) -> None:
    """Update the heatmap by merging new detections into existing clusters or creating new ones."""
    table = _get_table()
    pk = f"CAM#{building}"
    sk = f"SLOTS#{cam_num}"
    now = time.time()

    try:
        # 1. Fetch current learned state for this camera
        response = table.get_item(Key={"PK": pk, "SK": sk})
        slots_data = response.get("Item", {}).get("slots", [])

        # Load and FILTER OUT legacy pixel-based data (> 1.0)
        slots = []
        for s in slots_data:
            x1 = float(s["x1"])
            if x1 > 1.0:
                continue  # Skip zombie pixel data

            slots.append(
                Slot(
                    x1=x1,
                    y1=float(s["y1"]),
                    x2=float(s["x2"]),
                    y2=float(s["y2"]),
                    count=int(s["count"]),
                    last_seen=float(s["last_seen"]),
                )
            )

        # 2. Iterate through current vehicle detections and update clusters
        matched_slots: set[int] = set()
        for d in detections:
            # Skip tiny far-away detections (cars across the street, etc.)
            if (d.x2 - d.x1) * (d.y2 - d.y1) < MIN_DETECTION_AREA:
                continue

            best_slot = None
            best_idx = -1
            min_dist = float("inf")
            for idx, s in enumerate(slots):
                dist = s.distance_to(d)
                if dist < min_dist:
                    min_dist = dist
                    best_slot = s
                    best_idx = idx

            if best_slot is not None and min_dist < PROXIMITY_THRESHOLD and best_slot.iou(d) >= MERGE_IOU_THRESHOLD:
                alpha = max(1.0 / (best_slot.count + 1), ALPHA_FLOOR)
                best_slot.x1 = (1 - alpha) * best_slot.x1 + alpha * d.x1
                best_slot.y1 = (1 - alpha) * best_slot.y1 + alpha * d.y1
                best_slot.x2 = (1 - alpha) * best_slot.x2 + alpha * d.x2
                best_slot.y2 = (1 - alpha) * best_slot.y2 + alpha * d.y2
                best_slot.count = min(best_slot.count + 1, COUNT_CAP)
                best_slot.last_seen = now
                matched_slots.add(best_idx)
            else:
                matched_slots.add(len(slots))
                slots.append(Slot(x1=d.x1, y1=d.y1, x2=d.x2, y2=d.y2, count=1, last_seen=now))

        # Decay unconfirmed slots that had no matching detection this scan.
        # Confirmed slots are preserved — absence of a vehicle just means the spot is free.
        for idx, s in enumerate(slots):
            if idx not in matched_slots and s.count < CONFIRMATION_THRESHOLD:
                s.count = max(0, s.count - COUNT_DECAY)

        # 3. SELF-CLEANING: Merge clusters that are too close to each other
        # This prevents "cluster explosion" if detections are jittery.
        pruned_slots: list[Slot] = []
        for s in sorted(slots, key=lambda x: x.count, reverse=True):
            # See if this slot is a duplicate of one we've already kept
            is_duplicate = False
            for kept in pruned_slots:
                # If centers are within half the proximity threshold, it's a duplicate
                cx1, cy1 = (s.x1 + s.x2) / 2.0, (s.y1 + s.y2) / 2.0
                cx2, cy2 = (kept.x1 + kept.x2) / 2.0, (kept.y1 + kept.y2) / 2.0
                if ((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2) ** 0.5 < (PROXIMITY_THRESHOLD / 2):
                    is_duplicate = True
                    break
            if not is_duplicate:
                pruned_slots.append(s)

        slots = pruned_slots

        # 4. Garbage Collection: Remove fully-decayed slots and slots not seen for 7 days
        week_ago = now - (7 * 24 * 3600)
        slots = [s for s in slots if s.count > 0 and s.last_seen > week_ago]

        # 5. HARD CAP: Keep only the top 50 most frequent clusters
        # (No camera in this list has 50+ parking spots)
        slots = sorted(slots, key=lambda x: x.count, reverse=True)[:50]

        # 6. Persistence: Save the updated clusters back to DynamoDB
        decimal_slots = []
        for s in slots:
            decimal_slots.append(
                {
                    "x1": Decimal(str(round(s.x1, 4))),
                    "y1": Decimal(str(round(s.y1, 4))),
                    "x2": Decimal(str(round(s.x2, 4))),
                    "y2": Decimal(str(round(s.y2, 4))),
                    "count": s.count,
                    "last_seen": Decimal(str(int(s.last_seen))),
                }
            )

        ttl = int(now) + 14 * 86400  # Safety net: auto-expire if not updated for 14 days
        table.put_item(Item={"PK": pk, "SK": sk, "slots": decimal_slots, "updated_at": int(now), "ttl": ttl})
        logger.info("Updated heatmap for %s #%d: %d clusters", building, cam_num, len(slots))

    except Exception:
        logger.exception("Failed to update heatmap in DynamoDB")
