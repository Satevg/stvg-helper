import re
from typing import Any

import requests
from aws_lambda_powertools import Logger
from aws_lambda_powertools.metrics import MetricUnit
from metrics import metrics
from telegram import Update
from telegram.constants import ChatAction

logger = Logger(child=True)

# Matches X/Twitter status links across the common hostnames and mirrors.
# Captures the numeric tweet id.
TWITTER_URL_RE = re.compile(
    r"https?://(?:www\.|mobile\.)?" r"(?:x|twitter|fxtwitter|vxtwitter|fixupx|fixvx)\.com/" r"[^/\s]+/status/(\d+)",
    re.IGNORECASE,
)

# Public extraction APIs that return direct .mp4 URLs for a tweet.
# fxtwitter is primary; vxtwitter is the fallback if fxtwitter fails.
FXTWITTER_API = "https://api.fxtwitter.com/status/{id}"
VXTWITTER_API = "https://api.vxtwitter.com/Twitter/status/{id}"

# Telegram bots may upload files up to 50 MB. Larger videos are returned as a link.
TELEGRAM_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

_HTTP_TIMEOUT = 15


def extract_tweet_id(text: str) -> str | None:
    """Return the tweet id from the first X/Twitter status link in ``text``, if any."""
    match = TWITTER_URL_RE.search(text)
    return match.group(1) if match else None


def _video_url_from_fxtwitter(tweet_id: str) -> str | None:
    """Query the fxtwitter API and return the best-quality mp4 URL, or None."""
    resp = requests.get(
        FXTWITTER_API.format(id=tweet_id),
        timeout=_HTTP_TIMEOUT,
        headers={"User-Agent": "stvg-helper-bot"},
    )
    resp.raise_for_status()
    data = resp.json()
    videos = (data.get("tweet") or {}).get("media", {}).get("videos") or []
    mp4s = [v.get("url") for v in videos if v.get("url") and v.get("format") == "video/mp4"]
    if not mp4s:
        # Some responses omit `format`; fall back to any listed video url.
        mp4s = [v.get("url") for v in videos if v.get("url")]
    return mp4s[0] if mp4s else None


def _video_url_from_vxtwitter(tweet_id: str) -> str | None:
    """Query the vxtwitter API and return the best-quality mp4 URL, or None."""
    resp = requests.get(
        VXTWITTER_API.format(id=tweet_id),
        timeout=_HTTP_TIMEOUT,
        headers={"User-Agent": "stvg-helper-bot"},
    )
    resp.raise_for_status()
    data = resp.json()
    urls = [u for u in (data.get("mediaURLs") or []) if isinstance(u, str) and ".mp4" in u]
    return urls[0] if urls else None


def get_video_url(tweet_id: str) -> str | None:
    """Resolve a direct mp4 URL for ``tweet_id`` via fxtwitter, falling back to vxtwitter."""
    for name, resolver in (("fxtwitter", _video_url_from_fxtwitter), ("vxtwitter", _video_url_from_vxtwitter)):
        try:
            url = resolver(tweet_id)
            if url:
                return url
            logger.info("%s returned no video for tweet %s", name, tweet_id)
        except Exception:
            logger.exception("%s lookup failed for tweet %s", name, tweet_id)
    return None


def _download(url: str) -> bytes | None:
    """Download ``url``, returning the bytes or None if it exceeds the Telegram upload limit."""
    with requests.get(url, timeout=_HTTP_TIMEOUT, stream=True, headers={"User-Agent": "stvg-helper-bot"}) as resp:
        resp.raise_for_status()
        chunks = bytearray()
        for chunk in resp.iter_content(chunk_size=1 << 16):
            chunks.extend(chunk)
            if len(chunks) > TELEGRAM_MAX_UPLOAD_BYTES:
                return None
        return bytes(chunks)


async def xvideo_handler(update: Update, context: Any) -> None:
    """Reply with the video from an X/Twitter link contained in the incoming message."""
    if update.message is None or update.message.text is None:
        return

    tweet_id = extract_tweet_id(update.message.text)
    if tweet_id is None:
        return

    metrics.add_metric(name="XVideoRequest", unit=MetricUnit.Count, value=1)
    await update.message.chat.send_action(ChatAction.UPLOAD_VIDEO)

    try:
        video_url = get_video_url(tweet_id)
        if video_url is None:
            await update.message.reply_text("Couldn't find a video in that post.")
            return

        data = _download(video_url)
        if data is None:
            await update.message.reply_text(f"Video is too large to upload. Direct link:\n{video_url}")
            return

        await update.message.reply_video(video=data)
        metrics.add_metric(name="XVideoSuccess", unit=MetricUnit.Count, value=1)
    except Exception:
        logger.exception("Failed to handle X/Twitter video for tweet %s", tweet_id)
        await update.message.reply_text("Sorry, I couldn't download that video.")
