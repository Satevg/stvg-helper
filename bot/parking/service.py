import asyncio
import os
import random
import re
import time
from io import BytesIO
from typing import Any

import av
import requests
from aws_lambda_powertools import Logger
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.parameters import SSMProvider
from metrics import metrics
from parking.detector import Detection, detect_vehicles
from parking.heatmap import OCCUPIED_IOU_THRESHOLD, get_confirmed_slots, update_heatmap
from PIL import Image, ImageDraw
from telegram import Update

logger = Logger(child=True)

# SSM Parameter Store names for credentials
SSM_WATCHER_USERNAME_PARAM = os.environ.get("SSM_WATCHER_USERNAME_PARAM", "/stvg-helper/watcher-username")
SSM_WATCHER_PASSWORD_PARAM = os.environ.get("SSM_WATCHER_PASSWORD_PARAM", "/stvg-helper/watcher-password")

# Base URL for Flussonic Watcher
WATCHER_URL = os.environ.get("WATCHER_URL", "https://video.unet.by")

# (building title prefix, camera numbers) in search priority order.
# The bot will stop at the first camera that reports a free parking spot.
# PARKING_CAMERAS: list[tuple[str, list[int]]] = [
#     ("Авиационная 8", [1, 2, 3, 4, 7, 12]),
#     ("Авиационная 10", [1, 3, 4, 6, 8, 9, 10, 11]),
#     ("Б.Райт 1", [2, 3, 10]),
#     ("Б.Райт 3", [1, 2, 3]),
#     ("Б.Райт 5", [2, 5, 8]),
#     ("Б.Райт 7", [3, 4, 7, 8, 9]),
#     ("Яковлева 1", [2, 4, 7]),
# ]
PARKING_CAMERAS: list[tuple[str, list[int]]] = [
    ("Авиационная 8", [1, 2, 3, 4]),
    ("Авиационная 10", [3, 4, 10, 11]),
    ("Б.Райт 1", [2, 3, 10]),
]


_ssm: SSMProvider | None = None

# Camera cache (Phase 1A): avoid re-fetching the camera list on every warm invocation
_cameras_cache: list[dict[str, Any]] | None = None
_cameras_cache_ts: float = 0.0
_CAMERAS_CACHE_TTL: float = 300.0  # 5 minutes

# Camera lookup index (Phase 1B): O(1) lookups instead of O(N) scans
_cameras_index: dict[tuple[str, int], dict[str, Any]] = {}

# Staleness tracking (Phase 3A): prioritize cameras not scanned recently
_last_scanned: dict[tuple[str, int], float] = {}


def _get_ssm() -> SSMProvider:
    """Singleton for SSM provider."""
    global _ssm
    if _ssm is None:
        _ssm = SSMProvider()
    return _ssm


def get_watcher_username() -> str:
    """Fetch decrypted Watcher username from SSM."""
    return str(_get_ssm().get(SSM_WATCHER_USERNAME_PARAM, decrypt=True, max_age=3600))


def get_watcher_password() -> str:
    """Fetch decrypted Watcher password from SSM."""
    return str(_get_ssm().get(SSM_WATCHER_PASSWORD_PARAM, decrypt=True, max_age=3600))


def fetch_cameras() -> list[dict[str, Any]]:
    """Login to Watcher and fetch the full list of cameras (handles pagination)."""
    session = requests.Session()
    login_resp = session.post(
        f"{WATCHER_URL}/vsaas/api/v2/auth/login",
        json={"login": get_watcher_username(), "password": get_watcher_password()},
        timeout=10,
    )
    login_resp.raise_for_status()
    watcher_session = login_resp.json()["session"]

    all_cameras: list[dict[str, Any]] = []
    limit = 100
    offset = 0

    while True:
        cameras_resp = session.get(
            f"{WATCHER_URL}/vsaas/api/v2/cameras",
            headers={"X-Vsaas-Session": watcher_session},
            params={"limit": limit, "offset": offset},
            timeout=10,
        )
        cameras_resp.raise_for_status()
        batch: list[dict[str, Any]] = cameras_resp.json()

        if not batch:
            break

        all_cameras.extend(batch)
        if len(batch) < limit:
            break

        offset += limit

    logger.info("Fetched %d cameras total", len(all_cameras))
    return all_cameras


def fetch_cameras_cached() -> list[dict[str, Any]]:
    """Return the camera list, using a module-level cache with 5-minute TTL."""
    global _cameras_cache, _cameras_cache_ts
    now = time.monotonic()
    if _cameras_cache is not None and (now - _cameras_cache_ts) < _CAMERAS_CACHE_TTL:
        logger.info("Using cached cameras list (%d cameras)", len(_cameras_cache))
        return _cameras_cache
    cameras = fetch_cameras()
    _cameras_cache = cameras
    _cameras_cache_ts = now
    _build_index(cameras)
    return cameras


def _norm(s: str) -> str:
    """Lowercase and collapse dots/spaces to single space for fuzzy title matching."""
    return re.sub(r"[.\s]+", " ", s).lower().strip()


def _build_index(cameras: list[dict[str, Any]]) -> None:
    """Build a lookup index from (building, cam_num) to camera dict."""
    global _cameras_index
    _cameras_index = {}
    for cam in cameras:
        title = _norm(str(cam.get("title", "")))
        for building, cam_nums in PARKING_CAMERAS:
            building_norm = _norm(building)
            if building_norm not in title:
                continue
            for cn in cam_nums:
                cam_suffix = f"камера {cn:02d}"
                if cam_suffix in title:
                    _cameras_index[(building, cn)] = cam


def find_camera(cameras: list[dict[str, Any]], building: str, cam_num: int) -> dict[str, Any] | None:
    """Match a human-readable building+cam number to a specific Watcher camera object."""
    # Fast path: use pre-built index if available
    if _cameras_index:
        result = _cameras_index.get((building, cam_num))
        if result is None:
            logger.warning("No match for '%s — Камера %02d'", building, cam_num)
        return result

    # Fallback: linear scan (cold start before first fetch_cameras_cached call)
    building_norm = _norm(building)
    cam_suffix = f"камера {cam_num:02d}"
    for cam in cameras:
        title = _norm(str(cam.get("title", "")))
        if building_norm in title and cam_suffix in title:
            return cam
    logger.warning("No match for '%s — Камера %02d'", building, cam_num)
    return None


def _jpeg_from_mp4(mp4_bytes: bytes) -> bytes | None:
    """Decode the first video frame from an H.264 MP4 and return it as JPEG bytes."""
    try:
        with av.open(BytesIO(mp4_bytes), mode="r") as container:
            for frame in container.decode(video=0):
                img: Image.Image = frame.to_image()  # type: ignore[no-untyped-call]
                buf = BytesIO()
                img.save(buf, format="JPEG")
                return buf.getvalue()
    except Exception:
        logger.exception("Failed to decode MP4 frame with PyAV")
    return None


def _fetch_jpeg(cam: dict[str, Any]) -> bytes | None:
    """Fetch a short preview MP4 from the camera's streamer and extract a frame."""
    name = cam["name"]
    token = cam["playback_config"]["token"]
    server = cam["streamer_hostname"]

    try:
        url = f"https://{server}/{name}/preview.mp4"
        resp = requests.get(url, params={"token": token}, timeout=10)
        if resp.status_code == 200:
            return _jpeg_from_mp4(resp.content)
    except Exception:
        logger.exception("MP4 request failed for stream '%s'", name)

    logger.warning("No JPEG could be obtained for stream '%s'", name)
    return None


def _is_free(
    jpeg_bytes: bytes, building: str, cam_num: int, readonly: bool = False
) -> tuple[bool, list[Detection], list[Any]]:
    """Determine if parking is free using learned Heatmap slots.

    1. Runs vehicle detection on the current snapshot.
    2. Updates the Heatmap in DynamoDB (learning phase) - skipped if readonly.
    3. Fetches confirmed slots (areas where cars usually park).
    4. Compares detections with slots. If a slot has NO vehicle, it is FREE.
    """
    _, detections = detect_vehicles(jpeg_bytes)

    # Passive learning: Every scan (manual or automated) updates the parking clusters.
    # We skip this for manual requests to reduce latency.
    if not readonly:
        update_heatmap(building, cam_num, detections)

    # Active detection: Use confirmed (seen 5+ times) hotspots to check for emptiness
    slots = get_confirmed_slots(building, cam_num)
    if not slots:
        # No confirmed slots yet (bot is still learning this camera)
        return False, detections, []

    # A spot is free if no current detection overlaps a confirmed slot with IoU >= OCCUPIED_IOU_THRESHOLD
    free_slots = []
    for s in slots:
        occupied = any(s.iou(d) >= OCCUPIED_IOU_THRESHOLD for d in detections)
        if not occupied:
            free_slots.append(s)

    logger.info("Heatmap for %s #%d: %d confirmed slots, %d free", building, cam_num, len(slots), len(free_slots))
    return len(free_slots) > 0, detections, free_slots


async def _check_camera(
    cam: dict[str, Any], building: str, cam_num: int
) -> tuple[bool, bytes | None, list[Detection], list[Any]]:
    """Fetch a JPEG from a camera and check if parking is free (parallel-safe)."""
    loop = asyncio.get_running_loop()
    t0 = time.monotonic()
    jpeg = await loop.run_in_executor(None, _fetch_jpeg, cam)
    t_fetch = time.monotonic() - t0
    if jpeg is None:
        logger.info("fetch_jpeg for %s #%d: %.1fms (no image)", building, cam_num, t_fetch * 1000)
        return False, None, [], []

    t1 = time.monotonic()
    free, detections, free_slots = await loop.run_in_executor(None, _is_free, jpeg, building, cam_num, True)
    t_check = time.monotonic() - t1
    logger.info(
        "check_camera %s #%d: fetch=%.0fms is_free=%.0fms free=%s",
        building,
        cam_num,
        t_fetch * 1000,
        t_check * 1000,
        free,
    )
    return free, jpeg, detections, free_slots


def _annotate_jpeg(jpeg: bytes, detections: list[Detection], free_slots: list[Any]) -> bytes:
    """Draw semi-transparent green rectangles over learned spots that are currently empty."""
    img = Image.open(BytesIO(jpeg)).convert("RGB")
    w, h = img.size
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for s in free_slots:
        # Scale normalized coordinates back to pixels for drawing
        draw.rectangle(
            [s.x1 * w, s.y1 * h, s.x2 * w, s.y2 * h],
            fill=(0, 255, 0, 60),
            outline=(0, 255, 0, 255),
            width=2,
        )

    # Blend the overlay with the original image
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


async def update_heatmap_background() -> None:
    """Automated learning task triggered by EventBridge (e.g., every 5 minutes).

    Scans 4 cameras per invocation using staleness-weighted selection:
    cameras not scanned recently get much higher selection probability.
    """
    logger.info("Starting background heatmap update")
    loop = asyncio.get_running_loop()

    try:
        cameras = await loop.run_in_executor(None, fetch_cameras_cached)

        # Build a flat list of all building/camera pairs
        all_cams: list[tuple[str, int]] = []
        for building, cam_nums in PARKING_CAMERAS:
            for cn in cam_nums:
                all_cams.append((building, cn))

        # Staleness-weighted selection: cameras not scanned recently get higher weight
        now = time.monotonic()
        weights = [now - _last_scanned.get(cam_key, 0.0) for cam_key in all_cams]
        k = min(len(all_cams), 4)
        target_cams = random.choices(all_cams, weights=weights, k=k)
        # Deduplicate (choices can repeat)
        seen: set[tuple[str, int]] = set()
        unique_targets: list[tuple[str, int]] = []
        for cam_key in target_cams:
            if cam_key not in seen:
                seen.add(cam_key)
                unique_targets.append(cam_key)

        for building, cam_num in unique_targets:
            cam = find_camera(cameras, building, cam_num)
            if cam is None:
                continue

            jpeg = await loop.run_in_executor(None, _fetch_jpeg, cam)
            if jpeg is None:
                continue

            # This call updates the heatmap passive database
            await loop.run_in_executor(None, _is_free, jpeg, building, cam_num)
            _last_scanned[(building, cam_num)] = time.monotonic()
            logger.info("Background update complete for %s #%d", building, cam_num)

    except Exception:
        logger.exception("Error in background heatmap update")


async def parking_handler(update: Update, context: Any) -> None:
    """Telegram handler triggered by the 'Parking' button."""
    if update.message is None:
        return
    metrics.add_metric(name="ParkingManualInvokation", unit=MetricUnit.Count, value=1)
    status_msg = await update.message.reply_text("Ищу свободное место...")
    loop = asyncio.get_running_loop()
    t_start = time.monotonic()

    try:
        t0 = time.monotonic()
        cameras = await loop.run_in_executor(None, fetch_cameras_cached)
        logger.info("fetch_cameras: %.0fms", (time.monotonic() - t0) * 1000)

        checked = 0

        # Scan buildings in priority order, cameras within a building in parallel
        for building, cam_nums in PARKING_CAMERAS:
            # Resolve all cameras for this building
            tasks: list[tuple[int, dict[str, Any]]] = []
            for cam_num in cam_nums:
                cam = find_camera(cameras, building, cam_num)
                if cam is not None:
                    tasks.append((cam_num, cam))

            if not tasks:
                continue

            # Scan all cameras in this building concurrently
            results = await asyncio.gather(*[_check_camera(cam, building, cam_num) for cam_num, cam in tasks])

            for (cam_num, _cam), (free, jpeg, detections, free_slots) in zip(tasks, results):
                if jpeg is not None:
                    checked += 1
                if free and jpeg is not None:
                    logger.info(
                        "Free spot found at %s — Камера %02d (total %.0fms)",
                        building,
                        cam_num,
                        (time.monotonic() - t_start) * 1000,
                    )
                    photo = _annotate_jpeg(jpeg, detections, free_slots)
                    await status_msg.delete()
                    await update.message.reply_photo(
                        photo=BytesIO(photo),
                        caption=f"Свободное место! {building} — Камера {cam_num:02d}",
                    )
                    return

        total_ms = (time.monotonic() - t_start) * 1000
        if checked == 0:
            logger.warning("No JPEG snapshots were available from any matched camera (%.0fms)", total_ms)
            await status_msg.edit_text("Нет доступных снимков для анализа.")
        else:
            logger.info("No free spots found after checking %d cameras (%.0fms)", checked, total_ms)
            await status_msg.edit_text("Свободных мест не найдено.")

    except Exception:
        logger.exception("Unhandled error in parking handler")
        await status_msg.edit_text("Ошибка при поиске парковки.")
