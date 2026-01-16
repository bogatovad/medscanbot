import logging

from maxapi import Bot, Dispatcher

from app.config import settings

logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(settings.MAX_BOT_TOKEN)
dp = Dispatcher()


# @dp.bot_started()
# async def bot_started(event: BotStarted):
#     await event.bot.send_message(
#         chat_id=event.chat_id,
#         text="Привет! Отправь мне /start",
#     )
#
#
# # Обработчик команды /start
# @dp.message_created(Command('start'))
# async def hello(event: MessageCreated):
#     await event.message.answer("Чат-бот запущен. Двигаемся дальше")
#     # python -m app.bot.polling
