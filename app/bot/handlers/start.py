"""
Обработчики команд /start, /clear, /data, /state и кнопки «Назад в главное меню».
"""
import logging

from maxapi import F
from maxapi.types import BotStarted, Command, MessageCallback, MessageCreated
from maxapi.context import MemoryContext

from app.bot import dp
from app.bot.handlers.common import create_keyboard


@dp.on_started()
async def on_bot_started():
    logging.info("Бот стартовал!")


@dp.bot_started()
async def handle_bot_started(event: BotStarted):
    await event.bot.send_message(
        chat_id=event.chat_id,
        text="Привет! Отправь мне /start",
    )


@dp.message_created(Command("start"))
async def handle_start_command(event: MessageCreated, context: MemoryContext):
    await create_keyboard(event, context)


@dp.message_callback(F.callback.payload == "back_to_main")
async def handle_back_to_main(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    await create_keyboard(event, context)
