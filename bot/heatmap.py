import os
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import boto3
from aws_lambda_powertools import Logger
from detector import Detection

logger = Logger(child=True)

# DynamoDB table name for storing user data and parking clusters
TABLE_NAME = os.environ.get("DYNAMODB_TABLE", "stvg-helper")

# Distance threshold (normalized 0.0-1.0) to consider two detections as the same spot.
# 0.05 is approximately 5% of the frame width/height.
PROXIMITY_THRESHOLD = 0.05

# Minimum number of times a vehicle must be seen in a spot to "confirm" it as a real slot.
# This filters out temporary stops, moving cars, or transient delivery vehicles.
CONFIRMATION_THRESHOLD = 3


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
        # Calculate center points for both
        cx1, cy1 = (self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0
        cx2, cy2 = (d.x1 + d.x2) / 2.0, (d.y1 + d.y2) / 2.0
        # Euclidean distance in normalized coordinates
        dist: float = ((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2) ** 0.5
        return dist


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

        # 2. Iterate through current vehicle detections and update clusters
        for d in detections:
            # Find the closest existing slot for this detection
            best_slot = None
            min_dist = float("inf")
            for s in slots:
                dist = s.distance_to(d)
                if dist < min_dist:
                    min_dist = dist
                    best_slot = s

            # If the detection is close to an existing slot, merge it
            if best_slot and min_dist < PROXIMITY_THRESHOLD:
                # Update the slot coordinates using a moving average (alpha)
                # This causes the slot to drift toward the center of how people actually park.
                alpha = 1.0 / (best_slot.count + 1)
                best_slot.x1 = (1 - alpha) * best_slot.x1 + alpha * d.x1
                best_slot.y1 = (1 - alpha) * best_slot.y1 + alpha * d.y1
                best_slot.x2 = (1 - alpha) * best_slot.x2 + alpha * d.x2
                best_slot.y2 = (1 - alpha) * best_slot.y2 + alpha * d.y2
                best_slot.count += 1
                best_slot.last_seen = now
            else:
                # If no existing slot is nearby, create a new "potential" slot
                slots.append(Slot(x1=d.x1, y1=d.y1, x2=d.x2, y2=d.y2, count=1, last_seen=now))

        # 3. Garbage Collection: Remove slots not seen for 7 days (e.g., snow piles, temporary obstacles)
        week_ago = now - (7 * 24 * 3600)
        slots = [s for s in slots if s.last_seen > week_ago]

        # 4. Persistence: Save the updated clusters back to DynamoDB
        decimal_slots = []
        for s in slots:
            decimal_slots.append(
                {
                    "x1": Decimal(str(s.x1)),
                    "y1": Decimal(str(s.y1)),
                    "x2": Decimal(str(s.x2)),
                    "y2": Decimal(str(s.y2)),
                    "count": s.count,
                    "last_seen": Decimal(str(s.last_seen)),
                }
            )

        table.put_item(Item={"PK": pk, "SK": sk, "slots": decimal_slots, "updated_at": int(now)})
        logger.info("Updated heatmap for %s #%d: %d clusters", building, cam_num, len(slots))

    except Exception:
        logger.exception("Failed to update heatmap in DynamoDB")
