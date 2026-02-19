import asyncio
import base64
import logging
import os
import re
from functools import lru_cache
from io import BytesIO
from typing import Any

import anthropic
import av
import boto3
import requests
from PIL import Image
from telegram import Update

logger = logging.getLogger(__name__)

SSM_WATCHER_USERNAME_PARAM = os.environ.get("SSM_WATCHER_USERNAME_PARAM", "/stvg-helper/watcher-username")
SSM_WATCHER_PASSWORD_PARAM = os.environ.get("SSM_WATCHER_PASSWORD_PARAM", "/stvg-helper/watcher-password")
SSM_ANTHROPIC_API_KEY_PARAM = os.environ.get("SSM_ANTHROPIC_API_KEY_PARAM", "/stvg-helper/anthropic-api-key")

WATCHER_URL = os.environ.get("WATCHER_URL", "")

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


@lru_cache(maxsize=1)
def get_watcher_username() -> str:
    ssm = boto3.client("ssm")
    response = ssm.get_parameter(Name=SSM_WATCHER_USERNAME_PARAM, WithDecryption=True)
    return str(response["Parameter"]["Value"])


@lru_cache(maxsize=1)
def get_watcher_password() -> str:
    ssm = boto3.client("ssm")
    response = ssm.get_parameter(Name=SSM_WATCHER_PASSWORD_PARAM, WithDecryption=True)
    return str(response["Parameter"]["Value"])


@lru_cache(maxsize=1)
def get_anthropic_api_key() -> str:
    ssm = boto3.client("ssm")
    response = ssm.get_parameter(Name=SSM_ANTHROPIC_API_KEY_PARAM, WithDecryption=True)
    return str(response["Parameter"]["Value"])


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


async def _is_free(client: anthropic.AsyncAnthropic, image_bytes: bytes) -> bool:
    response = await client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=10,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": base64.standard_b64encode(image_bytes).decode(),
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Is there at least one free (empty, unoccupied) parking spot "
                            "visible in this image? Answer only 'yes' or 'no'."
                        ),
                    },
                ],
            }
        ],
    )
    logger.info(
        "Vision tokens: input=%d, output=%d",
        response.usage.input_tokens,
        response.usage.output_tokens,
    )
    content = response.content[0]
    if isinstance(content, anthropic.types.TextBlock):
        answer = content.text.strip().lower()
        logger.info("Vision answer: %r", answer)
        return answer.startswith("yes")
    logger.warning("Unexpected vision response type: %r", response.content)
    return False


async def parking_handler(update: Update, context: Any) -> None:
    assert update.message is not None
    status_msg = await update.message.reply_text("Ищу свободное место...")
    loop = asyncio.get_event_loop()

    try:
        cameras = await loop.run_in_executor(None, fetch_cameras)

        client = anthropic.AsyncAnthropic(api_key=get_anthropic_api_key())
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
                logger.info("Analyzing %s — Камера %02d with Claude Vision", building, cam_num)
                free = await _is_free(client, jpeg)

                if free:
                    logger.info("Free spot found at %s — Камера %02d", building, cam_num)
                    await status_msg.delete()
                    await update.message.reply_photo(
                        photo=BytesIO(jpeg),
                        caption=f"Свободное место! {building} — Камера {cam_num:02d}",
                    )
                    return

                logger.info("Occupied at %s — Камера %02d, continuing", building, cam_num)

        if checked == 0:
            logger.warning("No JPEG snapshots were available from any matched camera")
            await status_msg.edit_text("Нет доступных снимков для анализа.")
        else:
            logger.info("Checked %d cameras, no free spots found", checked)
            await status_msg.edit_text("Свободных мест не найдено.")

    except Exception:
        logger.exception("Unhandled error in parking handler")
        await status_msg.edit_text("Ошибка при поиске парковки.")
