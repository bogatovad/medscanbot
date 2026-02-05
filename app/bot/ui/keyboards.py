"""
Построение клавиатур (InlineKeyboardBuilder) для бота.
Все функции принимают готовые данные и возвращают builder и/или text.
"""
from datetime import date, datetime

from maxapi.types import CallbackButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from app.bot.constants import (
    BRANCHES_PER_PAGE,
    DEPARTMENTS_PER_PAGE,
    DOCTORS_PER_PAGE,
)


def build_main_keyboard(is_registered: bool) -> InlineKeyboardBuilder:
    """Главное меню: Текущая запись, Записаться на приём, Регистрация/Личный кабинет, Информация."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="📅 Текущая запись", payload="btn_current_appointment")
    )
    builder.row(
        CallbackButton(text="➕ Записаться на прием", payload="btn_make_appointment")
    )
    if is_registered:
        builder.row(
            CallbackButton(text="👤 Личный кабинет", payload="btn_personal_cabinet")
        )
    else:
        builder.row(
            CallbackButton(text="📝 Регистрация", payload="btn_lk_registration")
        )
    builder.row(
        CallbackButton(text="ℹ️ Информация о Медскан", payload="btn_info")
    )
    return builder


def build_personal_cabinet_keyboard() -> InlineKeyboardBuilder:
    """Клавиатура личного кабинета: Назад, Поменять логин и пароль, Удалить аккаунт."""
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="🔙 Назад", payload="back_to_main"))
    builder.row(
        CallbackButton(
            text="🔐 Поменять логин и пароль",
            payload="btn_change_credentials",
        )
    )
    builder.row(
        CallbackButton(text="🗑 Удалить аккаунт", payload="btn_delete_account")
    )
    return builder


def build_branches_keyboard(
    branches: list[dict],
    page: int,
) -> tuple[InlineKeyboardBuilder, str]:
    """Клавиатура выбора филиала с пагинацией. Возвращает (builder, text)."""
    total = len(branches)
    total_pages = (total + BRANCHES_PER_PAGE - 1) // BRANCHES_PER_PAGE if total > 0 else 1
    if page < 0:
        page = 0
    elif page >= total_pages:
        page = total_pages - 1
    start_idx = page * BRANCHES_PER_PAGE
    end_idx = min(start_idx + BRANCHES_PER_PAGE, total)
    page_branches = branches[start_idx:end_idx]

    builder = InlineKeyboardBuilder()
    for branch in page_branches:
        branch_id = branch.get("id")
        name = (branch.get("name") or "Без названия")[:30]
        if len((branch.get("name") or "")) > 30:
            name += "..."
        builder.row(
            CallbackButton(text=name, payload=f"branch_{branch_id}")
        )
    pagination = []
    if page > 0:
        pagination.append(
            CallbackButton(text="◀ Назад", payload=f"branches_page_{page - 1}")
        )
    if page < total_pages - 1:
        pagination.append(
            CallbackButton(text="Вперед ▶", payload=f"branches_page_{page + 1}")
        )
    if pagination:
        builder.row(*pagination)
    builder.row(CallbackButton(text="🔙 Назад", payload="back_to_main"))
    text = f"Выберите филиал:\n\nСтраница {page + 1} из {total_pages}"
    return builder, text


def build_departments_keyboard(
    departments: list[dict],
    page: int,
) -> tuple[InlineKeyboardBuilder, str]:
    """Клавиатура выбора отделения с пагинацией."""
    total = len(departments)
    total_pages = (total + DEPARTMENTS_PER_PAGE - 1) // DEPARTMENTS_PER_PAGE if total > 0 else 1
    if page < 0:
        page = 0
    elif page >= total_pages:
        page = total_pages - 1
    start_idx = page * DEPARTMENTS_PER_PAGE
    end_idx = min(start_idx + DEPARTMENTS_PER_PAGE, total)
    page_departments = departments[start_idx:end_idx]

    builder = InlineKeyboardBuilder()
    for dep in page_departments:
        dep_id = dep.get("id")
        name = (dep.get("name") or "Без названия")[:30]
        if len((dep.get("name") or "")) > 30:
            name += "..."
        builder.row(
            CallbackButton(text=name, payload=f"department_{dep_id}")
        )
    pagination = []
    if page > 0:
        pagination.append(
            CallbackButton(text="◀ Назад", payload=f"departments_page_{page - 1}")
        )
    if page < total_pages - 1:
        pagination.append(
            CallbackButton(text="Вперед ▶", payload=f"departments_page_{page + 1}")
        )
    if pagination:
        builder.row(*pagination)
    builder.row(
        CallbackButton(text="🔙 Назад к филиалам", payload="back_to_branches")
    )
    text = f"Выберите отделение:\n\nСтраница {page + 1} из {total_pages}"
    return builder, text


def build_doctors_keyboard(
    doctors: list[dict],
    page: int,
    branch_name: str,
    department_name: str,
) -> tuple[InlineKeyboardBuilder, str]:
    """Клавиатура выбора врача с пагинацией."""
    total = len(doctors)
    total_pages = (total + DOCTORS_PER_PAGE - 1) // DOCTORS_PER_PAGE if total > 0 else 1
    if page < 0:
        page = 0
    elif page >= total_pages:
        page = total_pages - 1
    start_idx = page * DOCTORS_PER_PAGE
    end_idx = min(start_idx + DOCTORS_PER_PAGE, total)
    page_doctors = doctors[start_idx:end_idx]

    builder = InlineKeyboardBuilder()
    for doc in page_doctors:
        dcode = doc.get("dcode") or doc.get("id")
        name = (doc.get("name") or "Врач")[:30]
        if len((doc.get("name") or "")) > 30:
            name += "..."
        builder.row(CallbackButton(text=name, payload=f"doctor_{dcode}"))
    pagination = []
    if page > 0:
        pagination.append(
            CallbackButton(text="◀ Назад", payload=f"doctors_page_{page - 1}")
        )
    if page < total_pages - 1:
        pagination.append(
            CallbackButton(text="Вперед ▶", payload=f"doctors_page_{page + 1}")
        )
    if pagination:
        builder.row(*pagination)
    builder.row(
        CallbackButton(text="🔙 Назад к отделениям", payload="back_to_departments")
    )
    text = (
        f"Выберите врача:\n\n"
        f"📍 Филиал: {branch_name}\n"
        f"🏥 Отделение: {department_name}\n\n"
        f"Страница {page + 1} из {total_pages}"
    )
    return builder, text


def build_calendar_keyboard(
    doctor_name: str,
    branch_name: str,
    department_name: str,
    days_ahead: int = 14,
) -> tuple[str, InlineKeyboardBuilder]:
    """Календарь выбора даты (кнопки по 3 в ряд). Возвращает (text, builder)."""
    from datetime import timedelta

    builder = InlineKeyboardBuilder()
    today = datetime.now().date()
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    buttons_row = []
    for i in range(days_ahead):
        d = today + timedelta(days=i)
        date_str = d.strftime("%Y%m%d")
        day_month = d.strftime("%d.%m")
        wd = weekdays[d.weekday()]
        buttons_row.append(
            CallbackButton(text=f"{day_month} {wd}", payload=f"date_{date_str}")
        )
        if len(buttons_row) == 3:
            builder.row(*buttons_row)
            buttons_row = []
    if buttons_row:
        builder.row(*buttons_row)
    builder.row(
        CallbackButton(text="🔙 Назад к врачам", payload="back_to_doctors")
    )
    text = (
        f"✅ Вы выбрали:\n"
        f"📍 Филиал: {branch_name}\n"
        f"🏥 Отделение: {department_name}\n"
        f"👨‍⚕️ Врач: {doctor_name}\n\n"
        f"📅 Выберите дату:"
    )
    return text, builder


def _get_start_time(time_str: str) -> str:
    if "-" in time_str:
        return time_str.split("-")[0].strip()
    return time_str


def format_schedule_info(
    intervals_data: dict,
    doctor_name: str,
    branch_name: str,
    department_name: str,
    selected_date: date | str,
    doctor_dcode: int | str,
) -> tuple[str, InlineKeyboardBuilder]:
    """
    Форматирует текст и клавиатуру выбора времени по данным get_reservation_intervals.
    Возвращает (text, builder).
    """
    if isinstance(selected_date, date):
        selected_date_str = selected_date.strftime("%Y%m%d")
        date_display = selected_date.strftime("%d.%m.%Y")
    else:
        selected_date_str = selected_date
        try:
            date_obj = datetime.strptime(selected_date_str, "%Y%m%d").date()
            date_display = date_obj.strftime("%d.%m.%Y")
        except (ValueError, TypeError):
            date_display = selected_date_str

    text_parts = [
        "✅ Вы выбрали:",
        f"📍 Филиал: {branch_name}",
        f"🏥 Отделение: {department_name}",
        f"👨‍⚕️ Врач: {doctor_name}",
        f"📅 Дата: {date_display}",
        "",
        "🕐 Доступное время:",
    ]

    builder = InlineKeyboardBuilder()
    data_list = intervals_data.get("data", [])
    date_intervals = []

    for item in data_list:
        if not isinstance(item, dict):
            continue
        for workdate_item in item.get("workdates", []):
            if not isinstance(workdate_item, dict) or selected_date_str not in workdate_item:
                continue
            date_data = workdate_item[selected_date_str]
            if not isinstance(date_data, list):
                continue
            for schedule_item in date_data:
                if not isinstance(schedule_item, dict):
                    continue
                if str(schedule_item.get("dcode", "")) != str(doctor_dcode):
                    continue
                schedident = schedule_item.get("schedident")
                for interval in schedule_item.get("intervals", []):
                    if not isinstance(interval, dict):
                        continue
                    if interval.get("isFree", False) and interval.get("time"):
                        date_intervals.append({
                            "time": interval["time"],
                            "schedident": schedident,
                            "workDate": selected_date_str,
                            "dcode": doctor_dcode,
                        })

    date_intervals.sort(key=lambda x: _get_start_time(x["time"]))

    if not date_intervals:
        text_parts.append("\n⏰ На выбранную дату свободное время отсутствует.")
        text_parts.append("Попробуйте выбрать другую дату.")
    else:
        text_parts.append("")

    for i in range(0, len(date_intervals), 2):
        row = date_intervals[i : i + 2]
        buttons = []
        for info in row:
            time_start = _get_start_time(info["time"]).replace(":", "")
            payload_data = f"{time_start}_{info['schedident']}_{info['workDate']}"
            buttons.append(
                CallbackButton(text=info["time"], payload=f"time_{payload_data}")
            )
        builder.row(*buttons)

    builder.row(
        CallbackButton(text="🔙 Назад к выбору даты", payload="back_to_calendar")
    )
    return "\n".join(text_parts), builder


def build_time_confirmation_keyboard() -> InlineKeyboardBuilder:
    """После выбора времени: Подтвердить запись, Назад к выбору даты."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="✅ Подтвердить запись", payload="btn_confirm_reservation")
    )
    builder.row(
        CallbackButton(text="🔙 Назад к выбору даты", payload="back_to_schedule")
    )
    return builder


def build_confirm_reservation_keyboard() -> InlineKeyboardBuilder:
    """После успешной записи: Подписать документы, В главное меню."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text="✍️ Подписать документы онлайн",
            payload="btn_sign_documents",
        )
    )
    builder.row(
        CallbackButton(text="🔙 В главное меню", payload="back_to_main")
    )
    return builder


def build_info_menu_keyboard() -> InlineKeyboardBuilder:
    """Меню информации: Миссия, Организации, Контакты, Назад."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="1. Миссия и ценности", payload="info_mission")
    )
    builder.row(
        CallbackButton(text="2. Организации", payload="info_organizations")
    )
    builder.row(
        CallbackButton(text="3. Контакты", payload="info_contacts")
    )
    builder.row(
        CallbackButton(text="🔙 Назад", payload="back_to_main")
    )
    return builder


def build_info_organizations_keyboard() -> InlineKeyboardBuilder:
    """Список организаций и Назад в меню информации."""
    builder = InlineKeyboardBuilder()
    for label, payload in [
        ("1. Хадасса", "info_hadassah"),
        ("2. Яуза", "info_yauza"),
        ("3. ООО Медскан", "info_medscan_llc"),
        ("4. Медасист Курск", "info_medassist_kursk"),
        ("5. Медикал он Групп", "info_medical_on_group"),
        ("6. KDL", "info_kdl"),
    ]:
        builder.row(CallbackButton(text=label, payload=payload))
    builder.row(CallbackButton(text="🔙 Назад", payload="btn_info"))
    return builder


def build_info_back_keyboard(back_payload: str) -> InlineKeyboardBuilder:
    """Одна кнопка «Назад» с заданным payload (btn_info или info_organizations)."""
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="🔙 Назад", payload=back_payload))
    return builder
