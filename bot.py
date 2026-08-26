"""Personal Telegram assistant on top of a headless OpenClaw brain.

Design:
  - This bot OWNS the Telegram connection (one token = one poller).
  - Slash commands, the command menu and inline buttons are handled HERE and are
    NEVER forwarded to OpenClaw.
  - Only plain text (and, later, voice) is sent to the OpenClaw agent, whose
    reply is relayed back.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.chat_action import ChatActionSender

import openclaw_brain as brain

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

TG_LIMIT = 4096

# Per-chat session suffix; bumping it on /new starts a fresh OpenClaw dialog.
_session_gen: dict[int, int] = defaultdict(int)


def session_id(chat_id: int) -> str:
    return f"tg-{chat_id}-{_session_gen[chat_id]}"


# --------------------------------------------------------------------------- #
# Owner-only gate: silently ignore everyone except OWNER_ID.
# --------------------------------------------------------------------------- #
class OwnerOnly(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        if OWNER_ID and user and user.id != OWNER_ID:
            return  # drop
        return await handler(event, data)


dp = Dispatcher()
dp.message.middleware(OwnerOnly())
dp.callback_query.middleware(OwnerOnly())


def main_menu() -> InlineKeyboardMarkup:
    """Inline buttons = our own functions (placeholders for now)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🆕 Новый диалог", callback_data="cb:new")],
            [InlineKeyboardButton(text="ℹ️ Что я умею", callback_data="cb:help")],
            [InlineKeyboardButton(text="✖️ Закрыть", callback_data="cb:close")],
        ]
    )


# --------------------------------------------------------------------------- #
# Commands (handled here, never sent to OpenClaw)
# --------------------------------------------------------------------------- #
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Я твой ассистент.\n\n"
        "• Пиши текстом или голосом — отвечу через OpenClaw.\n"
        "• Команды и кнопки (меню слева) — это мои функции, ИИ их не трогает.\n\n"
        "Открыть меню: /menu",
        reply_markup=main_menu(),
    )


@dp.message(Command("menu"))
async def cmd_menu(message: Message):
    await message.answer("Меню:", reply_markup=main_menu())


@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Я ассистент поверх OpenClaw.\n\n"
        "Текст/голос → идёт в ИИ-мозг и я возвращаю ответ.\n"
        "/menu — кнопки-функции\n"
        "/new — начать диалог заново\n"
        "/id — показать твой Telegram id"
    )


@dp.message(Command("new"))
async def cmd_new(message: Message):
    _session_gen[message.chat.id] += 1
    await message.answer("🆕 Начал новый диалог. Прошлый контекст забыт.")


@dp.message(Command("id"))
async def cmd_id(message: Message):
    await message.answer(f"Твой id: <code>{message.from_user.id}</code>")


# --------------------------------------------------------------------------- #
# Inline buttons (handled here, never sent to OpenClaw)
# --------------------------------------------------------------------------- #
@dp.callback_query(F.data == "cb:new")
async def cb_new(cq: CallbackQuery):
    _session_gen[cq.message.chat.id] += 1
    await cq.answer("Новый диалог")
    await cq.message.answer("🆕 Начал новый диалог. Прошлый контекст забыт.")


@dp.callback_query(F.data == "cb:help")
async def cb_help(cq: CallbackQuery):
    await cq.answer()
    await cq.message.answer(
        "Пиши текстом или голосом — отвечу через ИИ.\n"
        "Кнопки и команды — мои собственные функции."
    )


@dp.callback_query(F.data == "cb:close")
async def cb_close(cq: CallbackQuery):
    await cq.answer("Закрыто")
    try:
        await cq.message.delete()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Plain text -> OpenClaw brain. Anything starting with "/" is excluded so
# unknown slash commands are ignored (not forwarded to the AI).
# --------------------------------------------------------------------------- #
@dp.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message, bot: Bot):
    chat_id = message.chat.id
    try:
        async with ChatActionSender.typing(bot=bot, chat_id=chat_id):
            reply = await brain.ask(message.text, session_id(chat_id))
    except brain.BrainError as exc:
        log.warning("brain error: %s", exc)
        await message.answer("⚠️ Мозг не ответил. Проверь, запущен ли OpenClaw-шлюз.")
        return
    for i in range(0, len(reply), TG_LIMIT):
        await message.answer(reply[i:i + TG_LIMIT])


async def set_menu(bot: Bot):
    await bot.set_my_commands([
        BotCommand(command="menu", description="Кнопки-функции"),
        BotCommand(command="new", description="Новый диалог"),
        BotCommand(command="help", description="Помощь"),
        BotCommand(command="id", description="Мой Telegram id"),
    ])


async def main():
    bot = Bot(
        BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await set_menu(bot)
    log.info("bot starting (owner=%s)", OWNER_ID)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
