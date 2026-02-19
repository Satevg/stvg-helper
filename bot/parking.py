import asyncio
import logging
import os
from functools import lru_cache
from io import BytesIO
from typing import Any

import boto3
import requests
from telegram import Update

logger = logging.getLogger(__name__)

SSM_WATCHER_USERNAME_PARAM = os.environ.get("SSM_WATCHER_USERNAME_PARAM", "/stvg-helper/watcher-username")
SSM_WATCHER_PASSWORD_PARAM = os.environ.get("SSM_WATCHER_PASSWORD_PARAM", "/stvg-helper/watcher-password")

WATCHER_URL = os.environ.get("WATCHER_URL", "")


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


def fetch_parking_snapshot() -> bytes:
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
    cameras = cameras_resp.json()
    cam = cameras[0]

    token = cam["playback_config"]["token"]
    server = cam["streamer_hostname"]
    name = cam["name"]

    jpg_resp = session.get(f"https://{server}/{name}/preview.jpg", params={"token": token}, timeout=15)
    if jpg_resp.status_code == 200 and jpg_resp.content[:2] == b"\xff\xd8":
        logger.info("Got JPEG snapshot (%d bytes)", len(jpg_resp.content))
        return jpg_resp.content

    logger.info("JPEG not available (status=%d), falling back to MP4", jpg_resp.status_code)
    mp4_resp = session.get(f"https://{server}/{name}/preview.mp4", params={"token": token}, timeout=15)
    mp4_resp.raise_for_status()
    return mp4_resp.content


async def parking_handler(update: Update, context: Any) -> None:
    assert update.message is not None
    try:
        image_bytes = await asyncio.get_event_loop().run_in_executor(None, fetch_parking_snapshot)
        if image_bytes[:2] == b"\xff\xd8":
            await update.message.reply_photo(photo=BytesIO(image_bytes))
        else:
            await update.message.reply_video(video=BytesIO(image_bytes))
    except Exception:
        logger.exception("Error fetching parking snapshot")
        await update.message.reply_text("Could not fetch parking snapshot.")
