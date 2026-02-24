import asyncio
import json
import os
from typing import Any, TypeAlias

import anthropic
from aws_lambda_powertools import Logger
from aws_lambda_powertools.utilities.parameters import SSMProvider
from parking import parking_handler, update_heatmap_background
from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

logger = Logger()

SSM_BOT_TOKEN_PARAM = os.environ.get("SSM_BOT_TOKEN_PARAM", "/stvg-helper/telegram-bot-token")
SSM_ANTHROPIC_API_KEY_PARAM = os.environ.get("SSM_ANTHROPIC_API_KEY_PARAM", "/stvg-helper/anthropic-api-key")

AnyApplication: TypeAlias = Application[Any, Any, Any, Any, Any, Any]

_ssm = SSMProvider()


def get_bot_token() -> str:
    return str(_ssm.get(SSM_BOT_TOKEN_PARAM, decrypt=True, max_age=3600))


def get_anthropic_api_key() -> str:
    return str(_ssm.get(SSM_ANTHROPIC_API_KEY_PARAM, decrypt=True, max_age=3600))


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
    if update.message is None:
        return
    await update.message.reply_text("Hi! Use the menu below to get started.", reply_markup=MAIN_MENU)


async def menu_button_handler(update: Update, context: Any) -> None:
    if update.message is None:
        return
    text = update.message.text
    if text == "Hello":
        await update.message.reply_text("Hello there!")
    elif text == "Parking":
        await parking_handler(update, context)


async def claude_handler(update: Update, context: Any) -> None:
    if update.message is None or update.message.text is None:
        return

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


@logger.inject_lambda_context
def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    global _loop

    if event.get("source") == "aws.events":
        logger.info("Warmup ping — starting background learning")
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_loop)

        _loop.run_until_complete(update_heatmap_background())
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
