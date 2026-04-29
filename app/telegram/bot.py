from __future__ import annotations

import asyncio

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from app.config import get_settings
from app.logger import configure_logging, get_logger
from app.timeutil import market_open, now_ist

log = get_logger(__name__)


async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None:
        return
    await update.effective_chat.send_message(
        "AXIOM here. NSE/BSE only. /status for live state, /plan for tiers."
    )


async def cmd_status(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None:
        return
    ts = now_ist()
    await update.effective_chat.send_message(
        f"⏱️ {ts.isoformat()}\n📈 market_open={market_open(ts)}"
    )


async def cmd_plan(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None:
        return
    await update.effective_chat.send_message(
        "Plans:\n"
        "  Free      ₹0        Delayed signals\n"
        "  Basic     ₹999/mo   Equity signals\n"
        "  Premium   ₹2,999/mo F&O signals + App\n"
        "  Elite     ₹7,999/mo Auto-trade + all segments"
    )


def build_application() -> Application:
    s = get_settings()
    if not s.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
    app = Application.builder().token(s.telegram_bot_token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("plan", cmd_plan))
    return app


def main() -> None:
    configure_logging()
    app = build_application()
    log.info("telegram_bot_starting")
    asyncio.run(app.run_polling(allowed_updates=Update.ALL_TYPES))


if __name__ == "__main__":
    main()
