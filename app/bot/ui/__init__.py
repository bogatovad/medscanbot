"""
UI-слой: построение клавиатур и текстов сообщений.
"""
from app.bot.ui.keyboards import (
    build_branches_keyboard,
    build_calendar_keyboard,
    build_confirm_reservation_keyboard,
    build_departments_keyboard,
    build_doctors_keyboard,
    build_main_keyboard,
    build_personal_cabinet_keyboard,
    build_time_confirmation_keyboard,
    format_schedule_info,
)

__all__ = [
    "build_main_keyboard",
    "build_personal_cabinet_keyboard",
    "build_branches_keyboard",
    "build_departments_keyboard",
    "build_doctors_keyboard",
    "build_calendar_keyboard",
    "format_schedule_info",
    "build_time_confirmation_keyboard",
    "build_confirm_reservation_keyboard",
]
