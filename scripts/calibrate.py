#!/usr/bin/env python3
"""Dev-only tool: fetch live snapshots from all parking cameras and print coverage ratios.

Usage:
    # Uses AWS credentials from environment / ~/.aws
    uv run scripts/calibrate.py

    # Override model path if not running from repo root
    YOLO_MODEL_PATH=models/yolov8n.onnx uv run scripts/calibrate.py

Annotated images are saved to calibration_output/ for manual review.
Useful for tuning COVERAGE_THRESHOLD in bot/parking.py.
"""

import os
import sys
from pathlib import Path

# Allow importing bot modules directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))

from parking import PARKING_CAMERAS, PARKING_ZONES, _annotate_jpeg, _fetch_jpeg, _is_free, fetch_cameras  # noqa: E402

OUTPUT_DIR = Path(__file__).parent.parent / "calibration_output"


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    print("Fetching camera list from Watcher...")
    cameras = fetch_cameras()
    print(f"Found {len(cameras)} cameras.\n")

    from parking import find_camera
    from detector import detect_vehicles

    for building, cam_nums in PARKING_CAMERAS:
        for cam_num in cam_nums:
            cam = find_camera(cameras, building, cam_num)
            if cam is None:
                print(f"  [{building} — Камера {cam_num:02d}]  NOT FOUND")
                continue

            jpeg = _fetch_jpeg(cam)
            if jpeg is None:
                print(f"  [{building} — Камера {cam_num:02d}]  no snapshot")
                continue

            zones = PARKING_ZONES.get((building, cam_num))
            coverage, detections = detect_vehicles(jpeg)
            free, _ = _is_free(jpeg, zones)
            status = "FREE" if free else "occupied"
            print(
                f"  [{building} — Камера {cam_num:02d}]  "
                f"coverage={coverage:.2f}  detections={len(detections)}  zones={len(zones) if zones else 0}  → {status}"
            )

            slug = f"{building} cam{cam_num:02d} {status}".replace(" ", "_").replace(".", "")
            out_path = OUTPUT_DIR / f"{slug}.jpg"
            annotated = _annotate_jpeg(jpeg, detections, zones)
            out_path.write_bytes(annotated)
            print(f"    saved → {out_path}")


if __name__ == "__main__":
    main()
