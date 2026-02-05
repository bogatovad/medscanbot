"""
Общие функции для обработчиков (например, показ главного меню).
"""
from app.bot.constants import START_TEXT
from app.bot.services.user_service import is_registered
from app.bot.ui.keyboards import build_main_keyboard


async def create_keyboard(event, context):
    """Показать главное меню (текст + кнопки). Использует context.user_id для проверки регистрации."""
    user_id = context.user_id
    registered = await is_registered(user_id)
    builder = build_main_keyboard(registered)
    await event.message.answer(
        text=START_TEXT,
        attachments=[builder.as_markup()],
    )
