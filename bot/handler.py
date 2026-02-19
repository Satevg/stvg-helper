import asyncio
import json
import logging
import os
from functools import lru_cache
from typing import Any, TypeAlias

import anthropic
import boto3
from parking import parking_handler
from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SSM_BOT_TOKEN_PARAM = os.environ.get("SSM_BOT_TOKEN_PARAM", "/stvg-helper/telegram-bot-token")
SSM_ANTHROPIC_API_KEY_PARAM = os.environ.get("SSM_ANTHROPIC_API_KEY_PARAM", "/stvg-helper/anthropic-api-key")

AnyApplication: TypeAlias = Application[Any, Any, Any, Any, Any, Any]


@lru_cache(maxsize=1)
def get_bot_token() -> str:
    ssm = boto3.client("ssm")
    response = ssm.get_parameter(Name=SSM_BOT_TOKEN_PARAM, WithDecryption=True)
    return str(response["Parameter"]["Value"])


@lru_cache(maxsize=1)
def get_anthropic_api_key() -> str:
    ssm = boto3.client("ssm")
    response = ssm.get_parameter(Name=SSM_ANTHROPIC_API_KEY_PARAM, WithDecryption=True)
    return str(response["Parameter"]["Value"])


MAIN_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("Hello"), KeyboardButton("Parking")]],
    resize_keyboard=True,
)


def build_application() -> AnyApplication:
    token = get_bot_token()
    application = Application.builder().token(token).updater(None).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(MessageHandler(filters.Text(["Hello", "Parking"]), menu_button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, claude_handler))
    return application


async def start_command(update: Update, context: Any) -> None:
    assert update.message is not None
    await update.message.reply_text("Hi! Use the menu below to get started.", reply_markup=MAIN_MENU)


async def menu_button_handler(update: Update, context: Any) -> None:
    assert update.message is not None
    text = update.message.text
    if text == "Hello":
        await update.message.reply_text("Hello there!")
    elif text == "Parking":
        await parking_handler(update, context)


async def claude_handler(update: Update, context: Any) -> None:
    assert update.message is not None
    assert update.message.text is not None

    client = anthropic.AsyncAnthropic(api_key=get_anthropic_api_key())
    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": update.message.text}],
        )
        content = response.content[0]
        reply = content.text if isinstance(content, anthropic.types.TextBlock) else "Unexpected response."
    except Exception:
        logger.exception("Error calling Claude API")
        reply = "Sorry, something went wrong."

    await update.message.reply_text(reply)


_application: AnyApplication | None = None
_loop: asyncio.AbstractEventLoop | None = None


def get_application() -> AnyApplication:
    global _application
    if _application is None:
        _application = build_application()
    return _application


async def process_update(event: dict[str, Any]) -> dict[str, Any]:
    application = get_application()

    await application.initialize()
    update = Update.de_json(json.loads(event["body"]), application.bot)
    await application.process_update(update)

    return {"statusCode": 200, "body": json.dumps({"ok": True})}


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    global _loop

    if event.get("source") == "aws.events":
        logger.info("Warmup ping — priming application singleton")
        get_application()
        return {"statusCode": 200, "body": json.dumps({"ok": True})}

    if not event.get("body"):
        return {"statusCode": 400, "body": json.dumps({"error": "Empty body"})}

    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)

    try:
        return _loop.run_until_complete(process_update(event))
    except Exception:
        logger.exception("Error processing update")
        return {"statusCode": 200, "body": json.dumps({"ok": True})}
