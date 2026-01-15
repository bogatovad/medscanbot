import asyncio
import logging

from app.bot import bot, dp

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    # Если у бота установлены подписки на Webhook — события не будут приходить при polling.
    # Поэтому удаляем webhook перед start_polling.
    await bot.delete_webhook()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

