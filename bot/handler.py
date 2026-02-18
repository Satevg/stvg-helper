import asyncio
import json
import logging
import os
from functools import lru_cache

import boto3
from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SSM_BOT_TOKEN_PARAM = os.environ.get(
    "SSM_BOT_TOKEN_PARAM", "/stvg-helper/telegram-bot-token"
)


@lru_cache(maxsize=1)
def get_bot_token() -> str:
    ssm = boto3.client("ssm")
    response = ssm.get_parameter(Name=SSM_BOT_TOKEN_PARAM, WithDecryption=True)
    return response["Parameter"]["Value"]


MAIN_MENU = ReplyKeyboardMarkup(
    [[KeyboardButton("Hello"), KeyboardButton("Bye")]],
    resize_keyboard=True,
)


def build_application() -> Application:
    token = get_bot_token()
    application = Application.builder().token(token).updater(None).build()
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(
        MessageHandler(filters.Text(["Hello", "Bye"]), menu_button_handler)
    )
    return application


async def start_command(update: Update, context) -> None:
    await update.message.reply_text(
        "Hi! Use the menu below to get started.", reply_markup=MAIN_MENU
    )


async def menu_button_handler(update: Update, context) -> None:
    text = update.message.text
    if text == "Hello":
        await update.message.reply_text("Hello there!")
    elif text == "Bye":
        await update.message.reply_text("Goodbye! See you later.")


_application: Application | None = None
_loop: asyncio.AbstractEventLoop | None = None


def get_application() -> Application:
    global _application
    if _application is None:
        _application = build_application()
    return _application


async def process_update(event: dict) -> dict:
    application = get_application()

    await application.initialize()
    update = Update.de_json(json.loads(event["body"]), application.bot)
    await application.process_update(update)

    return {"statusCode": 200, "body": json.dumps({"ok": True})}


def lambda_handler(event: dict, context) -> dict:
    global _loop

    logger.info("Received event: %s", json.dumps(event))

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