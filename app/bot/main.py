import asyncio
import logging

from maxapi import Bot, Dispatcher
from maxapi.types import Command, MessageCreated

from app.config import settings

logging.basicConfig(level=logging.INFO)

bot = Bot(settings.MAX_BOT_TOKEN)
dp = Dispatcher()


@dp.message_created(Command('start'))
async def hello(event: MessageCreated):
    await event.message.answer(f"Привет из вебхука!")


async def main():
    await dp.handle_webhook(
        bot=bot,
        host='localhost',
        port=8080,
        log_level='critical'
    )


if __name__ == '__main__':
    asyncio.run(main())