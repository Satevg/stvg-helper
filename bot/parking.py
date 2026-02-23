import asyncio
import os
import re
from io import BytesIO
from typing import Any

import av
import requests
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.parameters import SSMProvider
from detector import Detection, detect_vehicles
from PIL import Image, ImageDraw
from telegram import Update

logger = Logger(child=True)

SSM_WATCHER_USERNAME_PARAM = os.environ.get("SSM_WATCHER_USERNAME_PARAM", "/stvg-helper/watcher-username")
SSM_WATCHER_PASSWORD_PARAM = os.environ.get("SSM_WATCHER_PASSWORD_PARAM", "/stvg-helper/watcher-password")

WATCHER_URL = os.environ.get("WATCHER_URL", "https://video.unet.by")

# Coverage ratio threshold: below this fraction of frame area occupied by vehicles → free spot likely
COVERAGE_THRESHOLD = 0.40

# Normalised (x1, y1, x2, y2) rectangle defining the drivable ground area of a camera frame.
Zone = tuple[float, float, float, float]

# Per-camera zone rectangles (normalised 0.0–1.0). Cameras not listed use the full frame.
# ("Building Name", camera_number): [(x1, y1, x2, y2), ...]
PARKING_ZONES: dict[tuple[str, int], list[Zone]] = {
    # Fill in after running scripts/zone_editor.py for each camera.
("Авиационная 10", 1): [(0.0508, 0.3348, 0.1592, 0.5393), (0.1817, 0.3215, 0.2875, 0.5052), (0.3092, 0.3467, 0.395, 0.5407), (0.4183, 0.3259, 0.515, 0.5304), (0.5242, 0.363, 0.5975, 0.5289), (0.6058, 0.3733, 0.7, 0.5274), (0.7108, 0.3822, 0.7675, 0.5126), (0.7767, 0.3926, 0.865, 0.5393)],
("Авиационная 10", 3): [(0.0325, 0.2104, 0.0783, 0.3333), (0.0992, 0.1911, 0.1367, 0.3244), (0.1525, 0.1926, 0.2067, 0.3244), (0.2275, 0.1837, 0.2858, 0.3067), (0.3325, 0.1393, 0.4017, 0.2874), (0.4558, 0.1704, 0.5367, 0.3185), (0.5683, 0.1111, 0.6708, 0.2933), (0.6925, 0.1126, 0.795, 0.3052)],
("Авиационная 10", 4): [(0.07, 0.157, 0.1675, 0.36), (0.1792, 0.1185, 0.2958, 0.2874), (0.0, 0.1467, 0.0575, 0.3319), (0.2958, 0.1007, 0.3883, 0.2622), (0.4033, 0.1067, 0.5033, 0.2756), (0.5183, 0.1333, 0.5958, 0.2933), (0.6167, 0.1333, 0.6725, 0.2919), (0.6842, 0.1393, 0.7325, 0.2815), (0.7408, 0.1807, 0.7742, 0.2874), (0.7908, 0.1926, 0.8242, 0.2889)],
("Авиационная 10", 6): [(0.0075, 0.1496, 0.095, 0.3526), (0.52, 0.0726, 0.5967, 0.203), (0.5933, 0.0859, 0.6483, 0.2119), (0.6542, 0.1052, 0.7, 0.1985), (0.71, 0.1274, 0.7625, 0.2133)],
("Авиационная 10", 8): [(0.4525, 0.0504, 0.5033, 0.16), (0.53, 0.0519, 0.5667, 0.1659), (0.61, 0.0741, 0.6442, 0.1689), (0.685, 0.083, 0.7483, 0.1807), (0.7708, 0.1407, 0.82, 0.2459), (0.85, 0.1822, 0.8983, 0.3185), (0.94, 0.2148, 0.995, 0.3793), (0.3875, 0.0593, 0.4192, 0.1467), (0.3475, 0.0681, 0.3742, 0.1259)],
("Авиационная 10", 9): [(0.9167, 0.1659, 0.985, 0.3881), (0.83, 0.1111, 0.895, 0.3037), (0.7217, 0.0844, 0.79, 0.2904), (0.6108, 0.0548, 0.7033, 0.2148), (0.5192, 0.0444, 0.5792, 0.1881), (0.4342, 0.0519, 0.485, 0.1644), (0.3842, 0.0533, 0.4233, 0.1615), (0.3042, 0.0533, 0.355, 0.1452)],
("Авиационная 10", 10): [(0.0525, 0.3585, 0.1567, 0.5941), (0.1725, 0.3985, 0.2725, 0.5615), (0.2958, 0.3393, 0.3983, 0.4815), (0.4192, 0.3096, 0.5025, 0.48), (0.5275, 0.2844, 0.6092, 0.4533), (0.6408, 0.3007, 0.695, 0.4193), (0.7183, 0.2859, 0.7817, 0.3867), (0.8058, 0.2726, 0.87, 0.3896), (0.8892, 0.2563, 0.9475, 0.3674)],
("Авиационная 10", 11): [(0.6783, 0.3511, 0.7625, 0.5007), (0.5942, 0.3526, 0.6492, 0.4815), (0.5125, 0.3348, 0.5742, 0.4563), (0.4475, 0.3333, 0.4925, 0.4474), (0.3158, 0.32, 0.3658, 0.4252), (0.1533, 0.3274, 0.1883, 0.4252), (0.2117, 0.3348, 0.26, 0.4222)],
}

# (building title prefix, camera numbers) in search priority order — stop at first free spot
PARKING_CAMERAS: list[tuple[str, list[int]]] = [
    ("Авиационная 8", [1, 2, 3, 4, 7, 12]),
    ("Авиационная 10", [1, 3, 4, 6, 8, 9, 10, 11]),
    ("Б. Райт 1", [2, 3, 10]),
    ("Б. Райт 3", [1, 2, 3]),
    ("Б. Райт 5", [2, 5, 8]),
    ("Б. Райт 7", [3, 4, 7, 8, 9]),
    ("Яковлева 1", [2, 4, 7]),
]


_ssm = SSMProvider()


def get_watcher_username() -> str:
    return str(_ssm.get(SSM_WATCHER_USERNAME_PARAM, decrypt=True, max_age=3600))


def get_watcher_password() -> str:
    return str(_ssm.get(SSM_WATCHER_PASSWORD_PARAM, decrypt=True, max_age=3600))


def fetch_cameras() -> list[dict[str, Any]]:
    session = requests.Session()
    login_resp = session.post(
        f"{WATCHER_URL}/vsaas/api/v2/auth/login",
        json={"login": get_watcher_username(), "password": get_watcher_password()},
        timeout=10,
    )
    login_resp.raise_for_status()
    watcher_session = login_resp.json()["session"]

    cameras_resp = session.get(
        f"{WATCHER_URL}/vsaas/api/v2/cameras",
        headers={"X-Vsaas-Session": watcher_session},
        timeout=10,
    )
    cameras_resp.raise_for_status()
    result: list[dict[str, Any]] = cameras_resp.json()
    return result


def _norm(s: str) -> str:
    """Lowercase and collapse dots/spaces to single space for fuzzy title matching."""
    return re.sub(r"[.\s]+", " ", s).lower().strip()


def find_camera(cameras: list[dict[str, Any]], building: str, cam_num: int) -> dict[str, Any] | None:
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


def _zone_coverage(detections: list[Detection], zones: list[Zone], img_w: int, img_h: int) -> float:
    """Coverage ratio of vehicle detections within the given zone rectangles."""
    zone_area = sum((x2 - x1) * img_w * (y2 - y1) * img_h for x1, y1, x2, y2 in zones)
    if zone_area <= 0:
        return 0.0
    covered = 0.0
    for d in detections:
        for x1n, y1n, x2n, y2n in zones:
            zx1, zy1 = x1n * img_w, y1n * img_h
            zx2, zy2 = x2n * img_w, y2n * img_h
            ix1, iy1 = max(d.x1, zx1), max(d.y1, zy1)
            ix2, iy2 = min(d.x2, zx2), min(d.y2, zy2)
            if ix2 > ix1 and iy2 > iy1:
                covered += (ix2 - ix1) * (iy2 - iy1)
    return min(covered / zone_area, 1.0)


def _is_free(jpeg_bytes: bytes, zones: list[Zone] | None = None) -> tuple[bool, list[Detection]]:
    """Return (is_free, detections). Free when vehicle coverage is below threshold."""
    coverage, detections = detect_vehicles(jpeg_bytes)
    if zones:
        img = Image.open(BytesIO(jpeg_bytes))
        coverage = _zone_coverage(detections, zones, *img.size)
    logger.info("Coverage: %.2f (zones=%d, detections=%d)", coverage, len(zones or []), len(detections))
    return coverage < COVERAGE_THRESHOLD, detections


_GRID_COLS = 6
_GRID_ROWS = 4


def _annotate_jpeg(jpeg: bytes, detections: list[Detection], zones: list[Zone] | None = None) -> bytes:
    """Highlight grid cells with no vehicle overlap in green (potential free spots).

    When zones are provided, also draws a yellow outline around each zone and skips
    grid cells that fall entirely outside every zone.
    """
    img = Image.open(BytesIO(jpeg)).convert("RGB")
    w, h = img.size
    cell_w, cell_h = w // _GRID_COLS, h // _GRID_ROWS

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    if zones:
        for x1n, y1n, x2n, y2n in zones:
            draw.rectangle([x1n * w, y1n * h, x2n * w - 1, y2n * h - 1], outline=(255, 220, 0, 255), width=2)

    for row in range(_GRID_ROWS):
        for col in range(_GRID_COLS):
            cx1, cy1 = col * cell_w, row * cell_h
            cx2, cy2 = cx1 + cell_w, cy1 + cell_h

            if zones and not any(
                x1n * w < cx2 and x2n * w > cx1 and y1n * h < cy2 and y2n * h > cy1 for x1n, y1n, x2n, y2n in zones
            ):
                continue

            occupied = any(d.x1 < cx2 and d.x2 > cx1 and d.y1 < cy2 and d.y2 > cy1 for d in detections)
            if not occupied:
                draw.rectangle([cx1, cy1, cx2 - 1, cy2 - 1], fill=(0, 255, 0, 60), outline=(0, 255, 0, 255), width=3)

    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


async def parking_handler(update: Update, context: Any) -> None:
    if update.message is None:
        return
    status_msg = await update.message.reply_text("Ищу свободное место...")
    loop = asyncio.get_running_loop()

    try:
        cameras = await loop.run_in_executor(None, fetch_cameras)

        checked = 0

        for building, cam_nums in PARKING_CAMERAS:
            for cam_num in cam_nums:
                cam = find_camera(cameras, building, cam_num)
                if cam is None:
                    continue

                jpeg = await loop.run_in_executor(None, _fetch_jpeg, cam)
                if jpeg is None:
                    continue

                checked += 1
                zones = PARKING_ZONES.get((building, cam_num))
                free, detections = await loop.run_in_executor(None, _is_free, jpeg, zones)

                if free:
                    logger.info("Free spot found at %s — Камера %02d", building, cam_num)
                    photo = _annotate_jpeg(jpeg, detections, zones)
                    await status_msg.delete()
                    await update.message.reply_photo(
                        photo=BytesIO(photo),
                        caption=f"Свободное место! {building} — Камера {cam_num:02d}",
                    )
                    return

        if checked == 0:
            logger.warning("No JPEG snapshots were available from any matched camera")
            await status_msg.edit_text("Нет доступных снимков для анализа.")
        else:
            await status_msg.edit_text("Свободных мест не найдено.")

    except Exception:
        logger.exception("Unhandled error in parking handler")
        await status_msg.edit_text("Ошибка при поиске парковки.")
