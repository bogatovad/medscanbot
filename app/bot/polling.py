import asyncio
import logging

from datetime import datetime, timedelta, date

from maxapi import F
from maxapi.context import MemoryContext, State, StatesGroup
from maxapi.types import BotStarted, Command, MessageCreated, CallbackButton, MessageCallback, BotCommand
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from app.providers.infoclinica_client import InfoClinicaClient
from app.config import settings
from app.bot import bot, dp
from app.schemas.infoclinica import (
    InfoClinicaLoginPayload,
    InfoClinicaRegistrationPayload
)
from app.bot.router import router
from app.bot.auth import authorize_user, MedscanAuthClient
import requests
import requests

logging.basicConfig(level=logging.INFO)
dp.include_routers(router)

start_text = '''Чат-бота Medscan 💙'''

BRANCHES_PER_PAGE = 5
DEPARTMENTS_PER_PAGE = 5
DOCTORS_PER_PAGE = 5


class Form(StatesGroup):
    name = State()
    age = State()


class RegistrationForm(StatesGroup):
    """Форма регистрации нового пользователя"""
    lastName = State()
    firstName = State()
    middleName = State()
    birthDate = State()
    email = State()
    phone = State()
    snils = State()
    gender = State()
    accept = State()  # Согласие на обработку перс. данных


class LoginForm(StatesGroup):
    """Форма входа существующего пользователя"""
    username = State()
    password = State()


@dp.on_started()
async def on_bot_started():
    logging.info('Бот стартовал!')


@dp.bot_started()
async def handle_bot_started(event: BotStarted):
    await event.bot.send_message(
        chat_id=event.chat_id,
        text='Привет! Отправь мне /start'
    )


@dp.message_created(Command('clear'))
async def handle_clear_command(event: MessageCreated, context: MemoryContext):
    await context.clear()
    await event.message.answer("Ваш контекст был очищен!")


@dp.message_created(Command('data'))
async def handle_data_command(event: MessageCreated, context: MemoryContext):
    data = await context.get_data()
    await event.message.answer(f"Ваша контекстная память: {str(data)}")


@dp.message_created(Command('context'))
@dp.message_created(Command('state'))
async def handle_state_command(event: MessageCreated, context: MemoryContext):
    data = await context.get_state()
    await event.message.answer(f"Ваше контекстное состояние: {str(data)}")


@dp.message_created(Command('start'))
async def handle_start_command(event: MessageCreated):
    builder = InlineKeyboardBuilder()

    builder.row(
        CallbackButton(
            text='📅 Текущая запись',
            payload='btn_current_appointment'
        )
    )
    builder.row(
        CallbackButton(
            text='➕ Записаться на прием',
            payload='btn_make_appointment'
        )
    )
    builder.row(
        CallbackButton(
            text='ℹ️ Информация о Медскан',
            payload='btn_info'
        )
    )

    await event.message.answer(
        text=start_text,
        attachments=[
            builder.as_markup(),
        ]
    )


async def create_keyboard(event):
    builder = InlineKeyboardBuilder()

    builder.row(
        CallbackButton(
            text='📅 Текущая запись',
            payload='btn_current_appointment'
        )
    )
    builder.row(
        CallbackButton(
            text='➕ Записаться на прием',
            payload='btn_make_appointment'
        )
    )
    builder.row(
        CallbackButton(
            text='ℹ️ Информация о Медскан',
            payload='btn_info'
        )
    )

    await event.message.answer(
        text=start_text,
        attachments=[
            builder.as_markup(),
        ]
    )


@dp.message_callback(F.callback.payload == 'btn_info')
async def handle_info_button(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    await event.message.answer(
        'АО «Медскан» – динамично развивающаяся группа компаний и один из лидеров '
        'негосударственного сектора здравоохранения в России. Медицинские '
        'учреждения холдинга предлагают полный спектр высокотехнологичной '
        'медицинской помощи по передовым мировым протоколам'
    )
    await create_keyboard(event)


@dp.message_callback(F.callback.payload == 'back_to_main')
async def handle_back_to_main(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    await create_keyboard(event)


@dp.message_callback(F.callback.payload == 'btn_current_appointment')
async def handle_current_appointment_button(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    await event.message.answer('Функция "Текущая запись" в разработке')
    await create_keyboard(event)


async def get_branches():
    """Получает список всех филиалов"""
    async with InfoClinicaClient(
        base_url=settings.INFOCLINICA_BASE_URL,
        cookies=settings.INFOCLINICA_COOKIES,
        timeout_seconds=settings.INFOCLINICA_TIMEOUT_SECONDS
    ) as client:
        result = await client.filial_list()
        data = result.json or {}
        return data.get("data", [])


async def create_branches_keyboard(event, context: MemoryContext, page: int = 0):
    """Создает клавиатуру со списком филиалов с пагинацией"""
    # Получаем список филиалов (кешируем в контексте или получаем заново)
    data = await context.get_data()
    branches = data.get('branches_list')
    
    if not branches:
        branches = await get_branches()
        await context.update_data(branches_list=branches, branches_page=0)
    
    total_branches = len(branches)
    total_pages = (total_branches + BRANCHES_PER_PAGE - 1) // BRANCHES_PER_PAGE if total_branches > 0 else 1
    
    # Корректируем страницу, если она выходит за границы
    if page < 0:
        page = 0
    elif page >= total_pages:
        page = total_pages - 1
    
    await context.update_data(branches_page=page)
    
    # Получаем филиалы для текущей страницы
    start_idx = page * BRANCHES_PER_PAGE
    end_idx = min(start_idx + BRANCHES_PER_PAGE, total_branches)
    page_branches = branches[start_idx:end_idx]
    
    builder = InlineKeyboardBuilder()
    
    # Добавляем кнопки с филиалами
    for branch in page_branches:
        branch_id = branch.get("id")
        branch_name = branch.get("name", "Без названия")
        # Ограничиваем длину названия для кнопки
        button_text = branch_name[:30] + "..." if len(branch_name) > 30 else branch_name
        builder.row(
            CallbackButton(
                text=button_text,
                payload=f'branch_{branch_id}'
            )
        )
    
    # Добавляем кнопки пагинации
    pagination_buttons = []
    if page > 0:
        pagination_buttons.append(
            CallbackButton(
                text='◀ Назад',
                payload=f'branches_page_{page - 1}'
            )
        )
    
    if page < total_pages - 1:
        pagination_buttons.append(
            CallbackButton(
                text='Вперед ▶',
                payload=f'branches_page_{page + 1}'
            )
        )
    
    if pagination_buttons:
        builder.row(*pagination_buttons)
    
    # Кнопка "Назад" в главное меню
    builder.row(
        CallbackButton(
            text='🔙 Назад',
            payload='back_to_main'
        )
    )
    
    text = f"Выберите филиал:\n\nСтраница {page + 1} из {total_pages}"
    
    return builder, text


@dp.message_callback(F.callback.payload == 'btn_make_appointment')
async def handle_make_appointment_button(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    
    # Очищаем предыдущие данные о филиалах
    await context.update_data(branches_list=None, branches_page=0)
    
    builder, text = await create_branches_keyboard(event, context, page=0)
    
    await event.message.answer(
        text=text,
        attachments=[builder.as_markup()]
    )


@dp.message_callback(F.callback.payload.startswith('branches_page_'))
async def handle_branches_pagination(event: MessageCallback, context: MemoryContext):
    # Извлекаем номер страницы из payload
    page = int(event.callback.payload.split('_')[-1])
    
    builder, text = await create_branches_keyboard(event, context, page=page)
    
    # Удаляем старое сообщение и отправляем новое с обновленной страницей
    await event.message.delete()
    await event.message.answer(
        text=text,
        attachments=[builder.as_markup()]
    )


async def get_departments(filial_id: int | None = None):
    """Получает список всех отделений с фильтрацией по филиалу"""
    async with InfoClinicaClient(
        base_url=settings.INFOCLINICA_BASE_URL,
        cookies=settings.INFOCLINICA_COOKIES,
        timeout_seconds=settings.INFOCLINICA_TIMEOUT_SECONDS
    ) as client:
        params = {}
        if filial_id:
            params["f"] = filial_id
        
        result = await client.reservation_departments(params=params if params else None)
        data = result.json or {}
        return data.get("data", [])


async def create_departments_keyboard(event, context: MemoryContext, page: int = 0):
    """Создает клавиатуру со списком отделений с пагинацией"""
    # Получаем список отделений (кешируем в контексте или получаем заново)
    data = await context.get_data()
    departments = data.get('departments_list')
    branch_id = data.get('selected_branch_id')
    cached_branch_id = data.get('departments_cached_branch_id')
    
    # Если кеш отсутствует или филиал изменился, загружаем заново
    if not departments or cached_branch_id != branch_id:
        filial_id = int(branch_id) if branch_id else None
        departments = await get_departments(filial_id=filial_id)
        await context.update_data(
            departments_list=departments,
            departments_page=0,
            departments_cached_branch_id=branch_id
        )
    
    total_departments = len(departments)
    total_pages = (total_departments + DEPARTMENTS_PER_PAGE - 1) // DEPARTMENTS_PER_PAGE if total_departments > 0 else 1
    
    # Корректируем страницу, если она выходит за границы
    if page < 0:
        page = 0
    elif page >= total_pages:
        page = total_pages - 1
    
    await context.update_data(departments_page=page)
    
    # Получаем отделения для текущей страницы
    start_idx = page * DEPARTMENTS_PER_PAGE
    end_idx = min(start_idx + DEPARTMENTS_PER_PAGE, total_departments)
    page_departments = departments[start_idx:end_idx]
    
    builder = InlineKeyboardBuilder()
    
    # Добавляем кнопки с отделениями
    for department in page_departments:
        department_id = department.get("id")
        department_name = department.get("name", "Без названия")
        # Ограничиваем длину названия для кнопки
        button_text = department_name[:30] + "..." if len(department_name) > 30 else department_name
        builder.row(
            CallbackButton(
                text=button_text,
                payload=f'department_{department_id}'
            )
        )
    
    # Добавляем кнопки пагинации
    pagination_buttons = []
    if page > 0:
        pagination_buttons.append(
            CallbackButton(
                text='◀ Назад',
                payload=f'departments_page_{page - 1}'
            )
        )
    
    if page < total_pages - 1:
        pagination_buttons.append(
            CallbackButton(
                text='Вперед ▶',
                payload=f'departments_page_{page + 1}'
            )
        )
    
    if pagination_buttons:
        builder.row(*pagination_buttons)
    
    # Кнопка "Назад" к выбору филиала
    builder.row(
        CallbackButton(
            text='🔙 Назад к филиалам',
            payload='back_to_branches'
        )
    )
    
    text = f"Выберите отделение:\n\nСтраница {page + 1} из {total_pages}"
    
    return builder, text


@dp.message_callback(F.callback.payload.startswith('branch_'))
async def handle_branch_selection(event: MessageCallback, context: MemoryContext):
    # Извлекаем ID филиала из payload
    branch_id = event.callback.payload.split('_')[-1]
    
    # Получаем информацию о филиале
    data = await context.get_data()
    branches = data.get('branches_list', [])
    
    selected_branch = None
    for branch in branches:
        if str(branch.get("id")) == branch_id:
            selected_branch = branch
            break
    
    if selected_branch:
        await context.update_data(selected_branch_id=branch_id)
        # Очищаем предыдущие данные об отделениях и врачах (так как филиал изменился)
        await context.update_data(
            departments_list=None,
            departments_page=0,
            departments_cached_branch_id=None,
            doctors_list=None,
            doctors_page=0,
            doctors_cached_branch_id=None,
            doctors_cached_department_id=None
        )
        
        branch_name = selected_branch.get("name", "Филиал")
        await event.message.delete()
        
        # Показываем список отделений
        builder, text = await create_departments_keyboard(event, context, page=0)
        await event.message.answer(
            text=f'Вы выбрали филиал: {branch_name}\n\n{text}',
            attachments=[builder.as_markup()]
        )
    else:
        await event.message.delete()
        await event.message.answer('Филиал не найден')


@dp.message_callback(F.callback.payload.startswith('departments_page_'))
async def handle_departments_pagination(event: MessageCallback, context: MemoryContext):
    # Извлекаем номер страницы из payload
    page = int(event.callback.payload.split('_')[-1])
    
    builder, text = await create_departments_keyboard(event, context, page=page)
    
    # Получаем название филиала для отображения
    data = await context.get_data()
    branch_id = data.get('selected_branch_id')
    branches = data.get('branches_list', [])
    branch_name = "Филиал"
    for branch in branches:
        if str(branch.get("id")) == branch_id:
            branch_name = branch.get("name", "Филиал")
            break
    
    # Удаляем старое сообщение и отправляем новое с обновленной страницей
    await event.message.delete()
    await event.message.answer(
        text=f'Вы выбрали филиал: {branch_name}\n\n{text}',
        attachments=[builder.as_markup()]
    )


async def get_doctors(filial_id: int | None = None, department_id: int | None = None):
    """Получает список всех врачей с фильтрацией по филиалу и отделению"""
    async with InfoClinicaClient(
        base_url=settings.INFOCLINICA_BASE_URL,
        cookies=settings.INFOCLINICA_COOKIES,
        timeout_seconds=settings.INFOCLINICA_TIMEOUT_SECONDS
    ) as client:
        params = {}
        if filial_id:
            params["filial"] = filial_id
        if department_id:
            params["departments"] = department_id
        
        result = await client.sdk_specialists_doctors(params=params if params else None)
        data = result.json or {}
        doctors = data.get("data", [])
        
        # Логируем структуру данных для отладки
        if doctors:
            logging.info(f"Получены врачи: filial={filial_id}, departments={department_id}, первый врач = {doctors[0] if doctors else None}")
        
        return doctors


async def create_doctors_keyboard(event, context: MemoryContext, page: int = 0):
    """Создает клавиатуру со списком врачей с пагинацией"""
    # Получаем список врачей (кешируем в контексте или получаем заново)
    data = await context.get_data()
    doctors = data.get('doctors_list')
    branch_id = data.get('selected_branch_id')
    department_id = data.get('selected_department_id')
    cached_branch_id = data.get('doctors_cached_branch_id')
    cached_department_id = data.get('doctors_cached_department_id')
    
    # Если кеш отсутствует или филиал/отделение изменилось, загружаем заново
    if not doctors or cached_branch_id != branch_id or cached_department_id != department_id:
        filial_id = int(branch_id) if branch_id else None
        dept_id = int(department_id) if department_id else None
        doctors = await get_doctors(filial_id=filial_id, department_id=dept_id)
        await context.update_data(
            doctors_list=doctors,
            doctors_page=0,
            doctors_cached_branch_id=branch_id,
            doctors_cached_department_id=department_id
        )
    
    total_doctors = len(doctors)
    total_pages = (total_doctors + DOCTORS_PER_PAGE - 1) // DOCTORS_PER_PAGE if total_doctors > 0 else 1
    
    # Корректируем страницу, если она выходит за границы
    if page < 0:
        page = 0
    elif page >= total_pages:
        page = total_pages - 1
    
    await context.update_data(doctors_page=page)
    
    # Получаем врачей для текущей страницы
    start_idx = page * DOCTORS_PER_PAGE
    end_idx = min(start_idx + DOCTORS_PER_PAGE, total_doctors)
    page_doctors = doctors[start_idx:end_idx]
    
    builder = InlineKeyboardBuilder()
    
    # Добавляем кнопки с врачами
    for doctor in page_doctors:
        # Используем dcode для идентификации врача (так как id может отсутствовать)
        doctor_dcode = doctor.get("dcode")
        doctor_name = doctor.get("name", "Без названия")
        # Ограничиваем длину названия для кнопки
        button_text = doctor_name[:30] + "..." if len(doctor_name) > 30 else doctor_name
        builder.row(
            CallbackButton(
                text=button_text,
                payload=f'doctor_{doctor_dcode}'
            )
        )
    
    # Добавляем кнопки пагинации
    pagination_buttons = []
    if page > 0:
        pagination_buttons.append(
            CallbackButton(
                text='◀ Назад',
                payload=f'doctors_page_{page - 1}'
            )
        )
    
    if page < total_pages - 1:
        pagination_buttons.append(
            CallbackButton(
                text='Вперед ▶',
                payload=f'doctors_page_{page + 1}'
            )
        )
    
    if pagination_buttons:
        builder.row(*pagination_buttons)
    
    # Кнопка "Назад" к выбору отделения
    builder.row(
        CallbackButton(
            text='🔙 Назад к отделениям',
            payload='back_to_departments'
        )
    )
    
    text = f"Выберите врача:\n\nСтраница {page + 1} из {total_pages}"
    
    return builder, text


@dp.message_callback(F.callback.payload.startswith('department_'))
async def handle_department_selection(event: MessageCallback, context: MemoryContext):
    # Извлекаем ID отделения из payload
    department_id = event.callback.payload.split('_')[-1]
    
    # Получаем информацию об отделении
    data = await context.get_data()
    departments = data.get('departments_list', [])
    
    selected_department = None
    for department in departments:
        if str(department.get("id")) == department_id:
            selected_department = department
            break
    
    if selected_department:
        await context.update_data(selected_department_id=department_id)
        # Очищаем предыдущие данные о врачах (так как отделение изменилось)
        await context.update_data(
            doctors_list=None,
            doctors_page=0,
            doctors_cached_department_id=None
        )
        
        department_name = selected_department.get("name", "Отделение")
        
        # Получаем название филиала
        branch_id = data.get('selected_branch_id')
        branches = data.get('branches_list', [])
        branch_name = "Филиал"
        for branch in branches:
            if str(branch.get("id")) == branch_id:
                branch_name = branch.get("name", "Филиал")
                break
        
        await event.message.delete()
        
        # Показываем список врачей
        builder, text = await create_doctors_keyboard(event, context, page=0)
        await event.message.answer(
            text=f'Вы выбрали:\n📍 Филиал: {branch_name}\n🏥 Отделение: {department_name}\n\n{text}',
            attachments=[builder.as_markup()]
        )
    else:
        await event.message.delete()
        await event.message.answer('Отделение не найдено')


@dp.message_callback(F.callback.payload.startswith('doctors_page_'))
async def handle_doctors_pagination(event: MessageCallback, context: MemoryContext):
    # Извлекаем номер страницы из payload
    page = int(event.callback.payload.split('_')[-1])
    
    builder, text = await create_doctors_keyboard(event, context, page=page)
    
    # Получаем информацию о выбранном филиале и отделении для отображения
    data = await context.get_data()
    branch_id = data.get('selected_branch_id')
    department_id = data.get('selected_department_id')
    branches = data.get('branches_list', [])
    departments = data.get('departments_list', [])
    
    branch_name = "Филиал"
    for branch in branches:
        if str(branch.get("id")) == branch_id:
            branch_name = branch.get("name", "Филиал")
            break
    
    department_name = "Отделение"
    for department in departments:
        if str(department.get("id")) == department_id:
            department_name = department.get("name", "Отделение")
            break
    
    # Удаляем старое сообщение и отправляем новое с обновленной страницей
    await event.message.delete()
    await event.message.answer(
        text=f'Вы выбрали:\n📍 Филиал: {branch_name}\n🏥 Отделение: {department_name}\n\n{text}',
        attachments=[builder.as_markup()]
    )


def add_30_minutes(time_str: str) -> str:
    """
    Добавляет 30 минут к времени в формате HH:MM
    Возвращает время в формате HH:MM
    
    Args:
        time_str: Время в формате HH:MM (например, "11:00")
    
    Returns:
        Время + 30 минут в формате HH:MM (например, "11:30")
    """
    try:
        # Парсим время
        hours, minutes = map(int, time_str.split(':'))
        
        # Добавляем 30 минут
        total_minutes = hours * 60 + minutes + 30
        
        # Вычисляем новые часы и минуты
        new_hours = (total_minutes // 60) % 24
        new_minutes = total_minutes % 60
        
        # Форматируем обратно в строку
        return f"{new_hours:02d}:{new_minutes:02d}"
    except (ValueError, AttributeError) as e:
        logging.error(f"Ошибка при добавлении 30 минут к времени {time_str}: {e}")
        return time_str


def make_reservation(
    session: requests.Session,
    reserve_data: dict,
    selected_date_str: str = None,
    selected_time_str: str = None
) -> tuple[bool, str]:
    """
    Выполняет запись на прием через авторизованную сессию
    
    Args:
        session: Авторизованная сессия requests.Session
        reserve_data: Данные для записи
    
    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        # Логируем данные для отладки
        logging.info(f"Данные для записи: {reserve_data}")
        # Собираем куки так же, как в auth.py
        cookies_dict = {}
        for cookie in session.cookies:
            cookies_dict[cookie.name] = cookie.value
        logging.info(f"Куки в сессии: {cookies_dict}")
        
        # Заголовки для запроса записи
        headers = {
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-US,en;q=0.9',
            'priority': 'u=1, i',
            'referer': 'https://medscan-t.infoclinica.ru/reservation',
            'sec-ch-ua': '"Chromium";v="143", "Not A(Brand";v="24"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Linux"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
            'wr2-apirequest': '_',
            'x-integration-type': 'PORTAL-WR2',
            'content-type': 'application/json',
        }
        
        # Устанавливаем заголовки в сессию
        session.headers.update(headers)
        
        # Отправляем запрос на запись (используем URL из примера)
        base_url = MedscanAuthClient.BASE_URL
        reserve_url = f"{base_url}/api/reservation/reserve"
        
        response = session.post(
            reserve_url,
            json=reserve_data,
            timeout=30
        )
        
        logging.info(f"Статус ответа: {response.status_code}")
        logging.info(f"Ответ сервера: {response.text[:500]}")
        
        if response.status_code == 200:
            try:
                response_data = response.json()
                # Проверяем успешность записи
                if response_data.get('success') or 'error' not in str(response_data).lower():
                    # Формируем сообщение с датой и временем
                    message = "✅ Запись на прием успешно создана!\n\n"
                    if selected_date_str and selected_time_str:
                        # Форматируем дату из YYYYMMDD в DD.MM.YYYY
                        try:
                            from datetime import datetime as dt
                            date_obj = dt.strptime(selected_date_str, "%Y%m%d")
                            formatted_date = date_obj.strftime("%d.%m.%Y")
                            message += f"📅 Дата: {formatted_date}\n"
                            message += f"🕐 Время: {selected_time_str}\n\n"
                        except:
                            # Если не удалось распарсить дату, используем как есть
                            message += f"📅 Дата: {selected_date_str}\n"
                            message += f"🕐 Время: {selected_time_str}\n\n"
                    message += "Запись подтверждена. Ожидайте подтверждения."
                    return True, message
                else:
                    error_msg = response_data.get('message', 'Неизвестная ошибка')
                    return False, f"❌ Ошибка при записи: {error_msg}"
            except:
                # Если ответ не JSON, но статус 200, считаем успешным
                message = "✅ Запись на прием успешно создана!\n\n"
                if selected_date_str and selected_time_str:
                    try:
                        from datetime import datetime as dt
                        date_obj = dt.strptime(selected_date_str, "%Y%m%d")
                        formatted_date = date_obj.strftime("%d.%m.%Y")
                        message += f"📅 Дата: {formatted_date}\n"
                        message += f"🕐 Время: {selected_time_str}\n\n"
                    except:
                        message += f"📅 Дата: {selected_date_str}\n"
                        message += f"🕐 Время: {selected_time_str}\n\n"
                message += "Запись подтверждена. Ожидайте подтверждения."
                return True, message
        else:
            try:
                error_data = response.json()
                error_msg = error_data.get('message', f'HTTP {response.status_code}')
            except:
                error_msg = f'HTTP {response.status_code}'
            
            # Проверяем, не занято ли время
            if 'занят' in error_msg.lower() or 'busy' in error_msg.lower() or 'занято' in error_msg.lower():
                return False, f"❌ Выбранное время уже занято. Пожалуйста, выберите другое время."
            
            return False, f"❌ Ошибка при записи: {error_msg}"
    
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка сети при записи: {e}")
        return False, f"❌ Ошибка соединения при записи. Попробуйте позже."
    except Exception as e:
        logging.error(f"Неизвестная ошибка при записи: {e}", exc_info=True)
        return False, f"❌ Произошла ошибка при записи: {str(e)}"


async def get_doctor_schedule(
    doctor_dcode: int | str | None = None,
    filial_id: int | str | None = None,
    online_mode: int = 1,
    start_date: date | None = None,
    end_date: date | None = None
):
    """Получает график работы врача через API reservation/schedule с GET запросом"""
    async with InfoClinicaClient(
        base_url=settings.INFOCLINICA_BASE_URL,
        cookies=settings.INFOCLINICA_COOKIES,
        timeout_seconds=settings.INFOCLINICA_TIMEOUT_SECONDS
    ) as client:
        # Если даты не указаны, используем сегодня и завтра
        if not start_date:
            start_date = datetime.now().date()
        if not end_date:
            end_date = start_date + timedelta(days=1)
        
        st = start_date.strftime("%Y%m%d")
        en = end_date.strftime("%Y%m%d")
        
        # Формируем query параметры
        params = {
            "st": st,
            "en": en,
            "doctor": str(doctor_dcode) if doctor_dcode else "",
        }
        
        # Добавляем filialId если передан
        if filial_id:
            params["filialId"] = str(filial_id)
        
        # Используем метод reservation_schedule с GET запросом
        result = await client.reservation_schedule(
            payload=None,
            params=params,
            use_get=True
        )
        
        return result.json or {}


def create_calendar_keyboard(doctor_name: str, branch_name: str, department_name: str, days_ahead: int = 14):
    """Создает календарь с кнопками для выбора даты"""
    builder = InlineKeyboardBuilder()
    
    today = datetime.now().date()
    
    # Названия дней недели для русского языка
    weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

    # Создаем кнопки для ближайших дней (по 3 кнопки в ряд)
    buttons_row = []
    for i in range(days_ahead):
        date = today + timedelta(days=i)
        date_str = date.strftime("%Y%m%d")
        
        # Форматируем дату для отображения: ДД.ММ (День недели)
        weekday = weekdays[date.weekday()]
        day_month = date.strftime("%d.%m")
        button_text = f"{day_month} {weekday}"
        
        buttons_row.append(
            CallbackButton(
                text=button_text,
                payload=f'date_{date_str}'
            )
        )
        
        # Добавляем ряд каждые 3 кнопки
        if len(buttons_row) == 3:
            builder.row(*buttons_row)
            buttons_row = []
    
    # Добавляем оставшиеся кнопки
    if buttons_row:
        builder.row(*buttons_row)
    
    # Кнопка "Назад" к врачам
    builder.row(
        CallbackButton(
            text='🔙 Назад к врачам',
            payload='back_to_doctors'
        )
    )
    
    text = (
        f'✅ Вы выбрали:\n'
        f'📍 Филиал: {branch_name}\n'
        f'🏥 Отделение: {department_name}\n'
        f'👨‍⚕️ Врач: {doctor_name}\n\n'
        f'📅 Выберите дату:'
    )
    
    return text, builder


def format_schedule_info(schedule_data: dict, doctor_name: str, branch_name: str, department_name: str, selected_date: date | str):
    """Форматирует информацию о графике работы врача и ближайших доступных временах с кнопками"""
    from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
    
    # Преобразуем дату в строку формата YYYYMMDD
    if isinstance(selected_date, date):
        selected_date_str = selected_date.strftime("%Y%m%d")
    else:
        selected_date_str = selected_date
    
    # Форматируем дату для отображения
    if isinstance(selected_date, date):
        date_display = selected_date.strftime("%d.%m.%Y")
    else:
        # Парсим строку YYYYMMDD в дату
        try:
            date_obj = datetime.strptime(selected_date_str, "%Y%m%d").date()
            date_display = date_obj.strftime("%d.%m.%Y")
        except:
            date_display = selected_date_str
    
    text_parts = [
        '✅ Вы выбрали:',
        f'📍 Филиал: {branch_name}',
        f'🏥 Отделение: {department_name}',
        f'👨‍⚕️ Врач: {doctor_name}',
        f'📅 Дата: {date_display}',
        '',
        '🕐 Доступное время:'
    ]
    
    # Создаем клавиатуру для выбора времени
    builder = InlineKeyboardBuilder()
    available_times = []
    
    # Извлекаем данные из ответа API
    data_list = schedule_data.get('data', [])
    
    # Собираем все доступные интервалы на выбранную дату
    date_intervals = []
    
    for item in data_list:
        if not isinstance(item, dict):
            continue
        
        intervals = item.get('intervals', [])
        for interval in intervals:
            # Проверяем, что интервал свободен, доступен и на выбранную дату
            work_date = str(interval.get('workDate', ''))
            is_free = interval.get('isFree', False)
            is_available = interval.get('isAvailable', False)
            
            if work_date == selected_date_str and is_free and is_available:
                start_interval = interval.get('startInterval', '')
                if start_interval:
                    # Сохраняем дополнительную информацию для последующего использования
                    interval_info = {
                        'time': start_interval,
                        'schedident': interval.get('schedident'),
                        'filial': interval.get('filial'),
                        'filialName': interval.get('filialName', ''),
                        'workDate': work_date,
                        'endInterval': interval.get('endInterval', '')
                    }
                    date_intervals.append(interval_info)
    
    # Сортируем интервалы по времени и убираем дубликаты
    # Группируем по времени (может быть несколько интервалов с одинаковым временем начала)
    time_map = {}
    for interval in date_intervals:
        time_key = interval['time']
        if time_key not in time_map:
            time_map[time_key] = interval
    
    # Формируем список уникальных времен и сортируем
    available_times_data = sorted(time_map.values(), key=lambda x: x['time'])
    available_times = [item['time'] for item in available_times_data]  # Берем все доступные времена
    
    if available_times:
        text_parts.append('')
    else:
        text_parts.append(f'\n⏰ На выбранную дату свободное время отсутствует.')
        text_parts.append(f'Попробуйте выбрать другую дату.')
    
    # Создаем кнопки для каждого времени (по 2 кнопки в ряд)
    for i in range(0, len(available_times), 2):
        row_times = available_times[i:i+2]
        buttons = []
        for time in row_times:
            # Формируем payload с информацией об интервале
            interval_data = time_map[time]
            payload_data = f"{time.replace(':', '')}_{interval_data['schedident']}_{interval_data['workDate']}"
            buttons.append(
                CallbackButton(
                    text=time,
                    payload=f'time_{payload_data}'
                )
            )
        builder.row(*buttons)
    
    # Кнопка "Назад" к выбору даты
    builder.row(
        CallbackButton(
            text='🔙 Назад к выбору даты',
            payload='back_to_calendar'
        )
    )
    
    text = '\n'.join(text_parts)
    return text, builder


@dp.message_callback(F.callback.payload.startswith('date_'))
async def handle_date_selection(event: MessageCallback, context: MemoryContext):
    """Обработчик выбора даты из календаря"""
    # Извлекаем дату из payload (формат: date_20250116)
    date_str = event.callback.payload.replace('date_', '')
    
    # Парсим дату из строки YYYYMMDD
    try:
        selected_date = datetime.strptime(date_str, "%Y%m%d").date()
    except ValueError:
        await event.message.answer('❌ Ошибка: неверный формат даты')
        return
    
    # Сохраняем выбранную дату в контексте
    await context.update_data(selected_date=date_str)
    
    # Получаем информацию о выбранных данных
    data = await context.get_data()
    branch_id = data.get('selected_branch_id')
    department_id = data.get('selected_department_id')
    doctor_id = data.get('selected_doctor_id')
    doctor_dcode = data.get('selected_doctor_dcode')
    branches = data.get('branches_list', [])
    departments = data.get('departments_list', [])
    doctors = data.get('doctors_list', [])
    
    branch_name = "Филиал"
    for branch in branches:
        if str(branch.get("id")) == branch_id:
            branch_name = branch.get("name", "Филиал")
            break
    
    department_name = "Отделение"
    for department in departments:
        if str(department.get("id")) == department_id:
            department_name = department.get("name", "Отделение")
            break
    
    doctor_name = "Врач"
    for doctor in doctors:
        if str(doctor.get("id")) == doctor_id or str(doctor.get("dcode")) == str(doctor_dcode):
            doctor_name = doctor.get("name", "Врач")
            break
    
    await event.message.delete()
    
    try:
        # Преобразуем ID в int, проверяя на None и строку 'None'
        def safe_int(value):
            if not value or value == 'None' or value == 'null':
                return None
            try:
                return int(value)
            except (ValueError, TypeError):
                return None
        
        # Получаем dcode врача из контекста
        if not doctor_dcode:
            # Если dcode не найден, пытаемся использовать doctor_id
            doctor_dcode = safe_int(doctor_id)
        
        # Получаем ID филиала
        filial_id = safe_int(branch_id)
        
        # Получаем график работы врача на выбранную дату
        schedule_data = await get_doctor_schedule(
            doctor_dcode=doctor_dcode,
            filial_id=filial_id,
            online_mode=1,
            start_date=selected_date,
            end_date=selected_date + timedelta(days=1)
        )
        
        # Форматируем информацию о графике (возвращает текст и клавиатуру)
        schedule_text, time_keyboard = format_schedule_info(
            schedule_data, 
            doctor_name, 
            branch_name, 
            department_name, 
            selected_date
        )
        
        # Отправляем информацию о графике с кнопками времени
        await event.message.answer(
            text=schedule_text,
            attachments=[time_keyboard.as_markup()]
        )
        
    except Exception as e:
        logging.error(f"Ошибка при получении расписания на дату: {e}")
        await event.message.answer(
            f'❌ Ошибка при загрузке расписания на выбранную дату.\n\n'
            f'Попробуйте выбрать другую дату или обратитесь в поддержку.'
        )


@dp.message_callback(F.callback.payload == 'back_to_calendar')
async def handle_back_to_calendar(event: MessageCallback, context: MemoryContext):
    """Возврат к выбору даты из календаря"""
    data = await context.get_data()
    branch_id = data.get('selected_branch_id')
    department_id = data.get('selected_department_id')
    doctor_id = data.get('selected_doctor_id')
    branches = data.get('branches_list', [])
    departments = data.get('departments_list', [])
    doctors = data.get('doctors_list', [])
    
    branch_name = "Филиал"
    for branch in branches:
        if str(branch.get("id")) == branch_id:
            branch_name = branch.get("name", "Филиал")
            break
    
    department_name = "Отделение"
    for department in departments:
        if str(department.get("id")) == department_id:
            department_name = department.get("name", "Отделение")
            break
    
    doctor_name = "Врач"
    doctor_dcode = data.get('selected_doctor_dcode')
    for doctor in doctors:
        if str(doctor.get("id")) == doctor_id or str(doctor.get("dcode")) == str(doctor_dcode):
            doctor_name = doctor.get("name", "Врач")
            break
    
    # Показываем календарь
    calendar_text, calendar_keyboard = create_calendar_keyboard(doctor_name, branch_name, department_name)
    
    await event.message.delete()
    await event.message.answer(
        text=calendar_text,
        attachments=[calendar_keyboard.as_markup()]
    )


@dp.message_callback(F.callback.payload.startswith('doctor_'))
async def handle_doctor_selection(event: MessageCallback, context: MemoryContext):
    # Извлекаем dcode врача из payload (так как используем dcode для идентификации)
    doctor_dcode_from_payload = event.callback.payload.split('_')[-1]
    
    # Получаем информацию о враче
    data = await context.get_data()
    doctors = data.get('doctors_list', [])
    
    selected_doctor = None
    # Ищем врача по dcode
    for doctor in doctors:
        doctor_dcode = str(doctor.get("dcode", ""))
        if doctor_dcode == doctor_dcode_from_payload:
            selected_doctor = doctor
            break
    
    if selected_doctor:
        # Сохраняем dcode врача (используем dcode как основной идентификатор)
        doctor_dcode = selected_doctor.get("dcode")
        doctor_id = selected_doctor.get("id") or doctor_dcode  # id может отсутствовать
        
        await context.update_data(
            selected_doctor_id=doctor_id,
            selected_doctor_dcode=doctor_dcode
        )
        
        doctor_name = selected_doctor.get("name", "Врач")
        
        # Получаем информацию о филиале и отделении
        branch_id = data.get('selected_branch_id')
        department_id = data.get('selected_department_id')
        branches = data.get('branches_list', [])
        departments = data.get('departments_list', [])
        
        branch_name = "Филиал"
        for branch in branches:
            if str(branch.get("id")) == branch_id:
                branch_name = branch.get("name", "Филиал")
                break
        
        department_name = "Отделение"
        for department in departments:
            if str(department.get("id")) == department_id:
                department_name = department.get("name", "Отделение")
                break
        
        await event.message.delete()
        
        # Показываем календарь для выбора даты
        calendar_text, calendar_keyboard = create_calendar_keyboard(doctor_name, branch_name, department_name)
        
        await event.message.answer(
            text=calendar_text,
            attachments=[calendar_keyboard.as_markup()]
        )

    else:
        await event.message.delete()
        await event.message.answer('Врач не найден')


@dp.message_callback(F.callback.payload == 'back_to_departments')
async def handle_back_to_departments(event: MessageCallback, context: MemoryContext):
    # Возвращаемся к списку отделений
    data = await context.get_data()
    current_page = data.get('departments_page', 0)
    branch_id = data.get('selected_branch_id')
    branches = data.get('branches_list', [])
    
    branch_name = "Филиал"
    for branch in branches:
        if str(branch.get("id")) == branch_id:
            branch_name = branch.get("name", "Филиал")
            break
    
    builder, text = await create_departments_keyboard(event, context, page=current_page)
    
    await event.message.delete()
    await event.message.answer(
        text=f'Вы выбрали филиал: {branch_name}\n\n{text}',
        attachments=[builder.as_markup()]
    )


@dp.message_callback(F.callback.payload == 'back_to_branches')
async def handle_back_to_branches(event: MessageCallback, context: MemoryContext):
    # Возвращаемся к списку филиалов
    data = await context.get_data()
    current_page = data.get('branches_page', 0)
    
    builder, text = await create_branches_keyboard(event, context, page=current_page)
    
    await event.message.delete()
    await event.message.answer(
        text=text,
        attachments=[builder.as_markup()]
    )


@dp.message_callback(F.callback.payload.startswith('time_'))
async def handle_time_selection(event: MessageCallback, context: MemoryContext):
    # Извлекаем данные из payload (формат: time_1700_30017859_20260116)
    # где 1700 - время, 30017859 - schedident, 20260116 - дата
    payload_parts = event.callback.payload.replace('time_', '').split('_')
    
    if len(payload_parts) >= 3:
        time_str = payload_parts[0]  # Время в формате HHMM
        schedident = payload_parts[1]  # ID расписания
        work_date = payload_parts[2]  # Дата в формате YYYYMMDD
        
        # Восстанавливаем формат времени (1700 -> 17:00)
        if len(time_str) == 4:
            selected_time = f"{time_str[:2]}:{time_str[2:]}"
        else:
            selected_time = time_str
        
        # Сохраняем информацию о выбранном времени
        await context.update_data(
            selected_time=selected_time,
            selected_schedident=schedident,
            selected_work_date=work_date
        )
    else:
        # Fallback для старого формата
        time_str = event.callback.payload.replace('time_', '')
        if len(time_str) == 4:
            selected_time = f"{time_str[:2]}:{time_str[2:]}"
        else:
            selected_time = time_str
        await context.update_data(selected_time=selected_time)
    
    # Получаем информацию о выбранных данных
    data = await context.get_data()
    branch_id = data.get('selected_branch_id')
    department_id = data.get('selected_department_id')
    doctor_id = data.get('selected_doctor_id')
    branches = data.get('branches_list', [])
    departments = data.get('departments_list', [])
    doctors = data.get('doctors_list', [])
    
    branch_name = "Филиал"
    for branch in branches:
        if str(branch.get("id")) == branch_id:
            branch_name = branch.get("name", "Филиал")
            break
    
    department_name = "Отделение"
    for department in departments:
        if str(department.get("id")) == department_id:
            department_name = department.get("name", "Отделение")
            break
    
    doctor_name = "Врач"
    for doctor in doctors:
        if str(doctor.get("id")) == doctor_id:
            doctor_name = doctor.get("name", "Врач")
            break
    
    # Сохраняем выбранное время
    await context.update_data(selected_time=selected_time)
    
    await event.message.delete()
    
    # Показываем кнопки выбора: есть аккаунт или новый пользователь
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text='✅ У меня есть аккаунт',
            payload='has_account'
        )
    )
    builder.row(
        CallbackButton(
            text='➕ Новый пользователь',
            payload='new_user'
        )
    )
    builder.row(
        CallbackButton(
            text='🔙 Назад к выбору даты',
            payload='back_to_schedule'
        )
    )
    
    await event.message.answer(
        text=f'✅ Вы выбрали время: {selected_time}\n\n'
        f'📍 Филиал: {branch_name}\n'
        f'🏥 Отделение: {department_name}\n'
        f'👨‍⚕️ Врач: {doctor_name}\n\n'
        f'Для продолжения нужно войти в систему или зарегистрироваться.',
        attachments=[builder.as_markup()]
    )


@dp.message_callback(F.callback.payload == 'back_to_doctors')
async def handle_back_to_doctors(event: MessageCallback, context: MemoryContext):
    # Возвращаемся к списку врачей
    data = await context.get_data()
    current_page = data.get('doctors_page', 0)
    branch_id = data.get('selected_branch_id')
    department_id = data.get('selected_department_id')
    branches = data.get('branches_list', [])
    departments = data.get('departments_list', [])
    
    branch_name = "Филиал"
    for branch in branches:
        if str(branch.get("id")) == branch_id:
            branch_name = branch.get("name", "Филиал")
            break
    
    department_name = "Отделение"
    for department in departments:
        if str(department.get("id")) == department_id:
            department_name = department.get("name", "Отделение")
            break
    
    builder, text = await create_doctors_keyboard(event, context, page=current_page)
    
    await event.message.delete()
    await event.message.answer(
        text=f'Вы выбрали:\n📍 Филиал: {branch_name}\n🏥 Отделение: {department_name}\n\n{text}',
        attachments=[builder.as_markup()]
    )


@dp.message_created(F.message.body.text, Form.name)
async def handle_name_input(event: MessageCreated, context: MemoryContext):
    await context.update_data(name=event.message.body.text)

    data = await context.get_data()

    await event.message.answer(f"Приятно познакомиться, {data['name'].title()}!")


@dp.message_created(F.message.body.text, Form.age)
async def handle_age_input(event: MessageCreated, context: MemoryContext):
    await context.update_data(age=event.message.body.text)

    await event.message.answer("Ого! А мне всего пару недель 😁")


@dp.message_callback(F.callback.payload == 'has_account')
async def handle_has_account(event: MessageCallback, context: MemoryContext):
    """Обработчик кнопки 'У меня есть аккаунт'"""
    await context.set_state(LoginForm.username)
    await event.message.delete()
    await event.message.answer('Введите ваш логин:')


@dp.message_callback(F.callback.payload == 'new_user')
async def handle_new_user(event: MessageCallback, context: MemoryContext):
    """Обработчик кнопки 'Новый пользователь' - начинаем регистрацию"""
    await context.set_state(RegistrationForm.lastName)
    await event.message.delete()
    await event.message.answer('Регистрация нового пользователя\n\nВведите вашу фамилию:')


@dp.message_created(F.message.body.text, LoginForm.username)
async def handle_login_username(event: MessageCreated, context: MemoryContext):
    """Обработка ввода логина"""
    await context.update_data(login_username=event.message.body.text)
    await context.set_state(LoginForm.password)
    await event.message.answer('Введите ваш пароль:')


@dp.message_created(F.message.body.text, LoginForm.password)
async def handle_login_password(event: MessageCreated, context: MemoryContext):
    """Обработка ввода пароля и выполнение входа"""
    data = await context.get_data()
    username = data.get('login_username')
    password = event.message.body.text
    
    try:
        # Выполняем вход через модуль авторизации (логика из auth.py)
        # Запускаем синхронную функцию в отдельном потоке
        result = await asyncio.to_thread(authorize_user, username, password)
        
        # Проверяем результат
        if result.get('success'):
            await context.set_state(None)
            
            # Формируем сообщение с информацией о пользователе
            user_info = []
            if result.get('full_name'):
                user_info.append(f'👤 Имя: {result.get("full_name")}')
            if result.get('email'):
                user_info.append(f'📧 Email: {result.get("email")}')
            if result.get('phone'):
                user_info.append(f'📱 Телефон: {result.get("phone")}')
            
            message = f'✅ Вход выполнен успешно!\n\n'
            if user_info:
                message += '\n'.join(user_info) + '\n\n'
            message += f'Логин: {username}'
            
            await event.message.answer(message)
            await create_keyboard(event)
            
            # Сохраняем данные сессии в контекст для дальнейшего использования
            await context.update_data(
                authenticated=True,
                user_id=result.get('user_id'),
                session_data=result
            )
            
            # Если есть выбранное время, выполняем запись на прием
            data = await context.get_data()
            selected_time = data.get('selected_time')
            selected_work_date = data.get('selected_work_date')
            selected_schedident = data.get('selected_schedident')
            selected_doctor_dcode = data.get('selected_doctor_dcode')
            selected_branch_id = data.get('selected_branch_id')
            selected_department_id = data.get('selected_department_id')
            
            if selected_time and selected_work_date and selected_schedident and selected_doctor_dcode:
                # Получаем сессию из результата авторизации
                session = result.get('session')
                if not session:
                    logging.error("Сессия не найдена в результате авторизации")
                    await event.message.answer(
                        '❌ Ошибка: сессия авторизации не найдена. Попробуйте войти снова.'
                    )
                    return
                
                # Проверяем, что сессия содержит куки
                if not session.cookies:
                    logging.error("Сессия не содержит куки")
                    await event.message.answer(
                        '❌ Ошибка: сессия не содержит куки авторизации. Попробуйте войти снова.'
                    )
                    return
                
                # Собираем куки так же, как в auth.py
                cookies_list = [cookie.name for cookie in session.cookies]
                logging.info(f"Используем сессию с куками: {cookies_list}")
                
                if session:
                    try:
                        # Получаем интервалы для получения depnum и проверки свободности
                        # Используем InfoClinicaClient для получения интервалов
                        async with InfoClinicaClient(
                            base_url=settings.INFOCLINICA_BASE_URL,
                            cookies=settings.INFOCLINICA_COOKIES,
                            timeout_seconds=settings.INFOCLINICA_TIMEOUT_SECONDS
                        ) as client:
                            # Получаем интервалы на выбранную дату
                            # Используем следующий день как en для получения интервалов
                            from datetime import datetime as dt
                            work_date_obj = dt.strptime(selected_work_date, "%Y%m%d").date()
                            next_day = (work_date_obj + timedelta(days=1)).strftime("%Y%m%d")
                            
                            intervals_result = await client.get_reservation_intervals(
                                st=selected_work_date,
                                en=next_day,
                                dcode=selected_doctor_dcode,
                                online_mode=0
                            )
                            
                            if intervals_result.status_code == 200 and intervals_result.json:
                                intervals = intervals_result.json
                                
                                # Ищем нужный интервал по времени и schedident
                                depnum = None
                                found_interval = None
                                
                                # Интервалы могут быть в разных форматах, проверяем оба
                                intervals_list = intervals if isinstance(intervals, list) else intervals.get('intervals', []) if isinstance(intervals, dict) else []
                                
                                for interval in intervals_list:
                                    interval_schedident = interval.get('schedident') or interval.get('schedIdent')
                                    interval_time = interval.get('startInterval') or interval.get('start')
                                    
                                    # Проверяем совпадение по schedident и времени
                                    if (str(interval_schedident) == str(selected_schedident) and 
                                        interval_time == selected_time):
                                        depnum = interval.get('depnum') or interval.get('depNum')
                                        found_interval = interval
                                        break
                                
                                if not depnum and intervals_list:
                                    # Если не нашли точное совпадение, берем первый интервал с нужным временем
                                    for interval in intervals_list:
                                        interval_time = interval.get('startInterval') or interval.get('start')
                                        if interval_time == selected_time:
                                            depnum = interval.get('depnum') or interval.get('depNum')
                                            found_interval = interval
                                            break
                                
                                if not depnum:
                                    # Если depnum не найден, используем selected_department_id
                                    depnum = selected_department_id
                                
                                # Проверяем, свободен ли интервал
                                if found_interval:
                                    is_free = found_interval.get('isFree', True)
                                    if not is_free:
                                        await event.message.answer(
                                            f'❌ Выбранное время уже занято. Пожалуйста, выберите другое время.'
                                        )
                                        return
                                
                                # Вычисляем время окончания (start + 30 минут)
                                end_time = add_30_minutes(selected_time)
                                
                                # Формируем данные для записи
                                reserve_data = {
                                    "date": selected_work_date,
                                    "dcode": int(selected_doctor_dcode),
                                    "en": end_time,
                                    "filial": int(selected_branch_id) if selected_branch_id else 0,
                                    "onlineType": 0,
                                    "schedident": int(selected_schedident),
                                    "st": selected_time,
                                    "depnum": int(depnum) if depnum else 0,
                                    "refid": ""  # Добавляем обязательное поле refid (может быть пустым)
                                }
                                
                                # Логируем данные для отладки
                                logging.info(f"Формируем запись на прием: {reserve_data}")
                                logging.info(f"Сессия доступна: {session is not None}")
                                if session:
                                    # Собираем куки так же, как в auth.py
                                    cookies_list = [cookie.name for cookie in session.cookies]
                                    logging.info(f"Куки в сессии: {cookies_list}")
                                
                                # Выполняем запись (синхронная функция в отдельном потоке)
                                success, reservation_message = await asyncio.to_thread(
                                    make_reservation, session, reserve_data, selected_work_date, selected_time
                                )
                                
                                if success:
                                    await event.message.answer(reservation_message)
                                else:
                                    await event.message.answer(reservation_message)
                            else:
                                await event.message.answer(
                                    '⚠️ Не удалось проверить доступность времени. Попробуйте позже.'
                                )
                    except Exception as e:
                        logging.error(f"Ошибка при выполнении записи: {e}", exc_info=True)
                        await event.message.answer(
                            f'⚠️ Произошла ошибка при создании записи: {str(e)}\n\n'
                            f'Попробуйте позже или обратитесь в поддержку.'
                        )
        else:
            error_msg = result.get('error', 'Ошибка входа')
            await event.message.answer(
                f'❌ Ошибка входа: {error_msg}\n\n'
                f'Попробуйте еще раз.'
            )
    except Exception as e:
        logging.error(f"Ошибка при входе: {e}", exc_info=True)
        await event.message.answer(
            f'❌ Произошла ошибка при входе.\n\n'
            f'Попробуйте позже или обратитесь в поддержку.'
        )


@dp.message_created(F.message.body.text, RegistrationForm.lastName)
async def handle_registration_lastName(event: MessageCreated, context: MemoryContext):
    """Обработка ввода фамилии"""
    await context.update_data(reg_lastName=event.message.body.text)
    await context.set_state(RegistrationForm.firstName)
    await event.message.answer('Введите ваше имя:')


@dp.message_created(F.message.body.text, RegistrationForm.firstName)
async def handle_registration_firstName(event: MessageCreated, context: MemoryContext):
    """Обработка ввода имени"""
    await context.update_data(reg_firstName=event.message.body.text)
    await context.set_state(RegistrationForm.middleName)
    await event.message.answer('Введите ваше отчество (если есть, иначе отправьте "-"):')


@dp.message_created(F.message.body.text, RegistrationForm.middleName)
async def handle_registration_middleName(event: MessageCreated, context: MemoryContext):
    """Обработка ввода отчества"""
    middle_name = event.message.body.text if event.message.body.text != "-" else None
    await context.update_data(reg_middleName=middle_name)
    await context.set_state(RegistrationForm.birthDate)
    await event.message.answer('Введите дату рождения (формат: ДД.ММ.ГГГГ, например: 01.01.1990):')


@dp.message_created(F.message.body.text, RegistrationForm.birthDate)
async def handle_registration_birthDate(event: MessageCreated, context: MemoryContext):
    """Обработка ввода даты рождения"""
    await context.update_data(reg_birthDate=event.message.body.text)
    await context.set_state(RegistrationForm.email)
    await event.message.answer('Введите ваш email:')


@dp.message_created(F.message.body.text, RegistrationForm.email)
async def handle_registration_email(event: MessageCreated, context: MemoryContext):
    """Обработка ввода email"""
    await context.update_data(reg_email=event.message.body.text)
    await context.set_state(RegistrationForm.phone)
    await event.message.answer('Введите ваш телефон в формате: +7(000)000-00-00:')


def validate_phone(phone: str) -> bool:
    """Валидация телефона в формате +7(000)000-00-00"""
    import re
    pattern = r'^\+7\(\d{3}\)\d{3}-\d{2}-\d{2}$'
    return bool(re.match(pattern, phone))


@dp.message_created(F.message.body.text, RegistrationForm.phone)
async def handle_registration_phone(event: MessageCreated, context: MemoryContext):
    """Обработка ввода телефона с валидацией"""
    phone = event.message.body.text
    
    if not validate_phone(phone):
        await event.message.answer(
            '❌ Неверный формат телефона!\n\n'
            'Пожалуйста, введите телефон в формате: +7(000)000-00-00\n'
            'Например: +7(999)123-45-67'
        )
        return  # Остаемся в том же состоянии
    
    await context.update_data(reg_phone=phone)
    await context.set_state(RegistrationForm.snils)
    await event.message.answer('Введите ваш СНИЛС:')


@dp.message_created(F.message.body.text, RegistrationForm.snils)
async def handle_registration_snils(event: MessageCreated, context: MemoryContext):
    """Обработка ввода СНИЛС"""
    await context.update_data(reg_snils=event.message.body.text)
    await context.set_state(RegistrationForm.gender)
    await event.message.answer('Введите ваш пол (1 - мужской, 2 - женский):')


@dp.message_created(F.message.body.text, RegistrationForm.gender)
async def handle_registration_gender(event: MessageCreated, context: MemoryContext):
    """Обработка ввода пола"""
    gender = event.message.body.text
    if gender not in ['1', '2']:
        await event.message.answer(
            '❌ Неверное значение!\n\n'
            'Введите 1 для мужского пола или 2 для женского пола.'
        )
        return
    
    await context.update_data(reg_gender=int(gender))
    await context.set_state(RegistrationForm.accept)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text='✅ Согласен',
            payload='accept_personal_data'
        ),
        CallbackButton(
            text='❌ Не согласен',
            payload='reject_personal_data'
        )
    )
    
    await event.message.answer(
        'Согласны ли вы на обработку персональных данных?',
        attachments=[builder.as_markup()]
    )


@dp.message_callback(F.callback.payload == 'accept_personal_data')
async def handle_accept_personal_data(event: MessageCallback, context: MemoryContext):
    """Обработка согласия на обработку персональных данных"""
    await context.update_data(reg_accept=True)
    
    # Получаем все данные регистрации
    data = await context.get_data()
    
    try:
        # Выполняем регистрацию через API
        async with InfoClinicaClient(
            base_url=settings.INFOCLINICA_BASE_URL,
            cookies=settings.INFOCLINICA_COOKIES,
            timeout_seconds=settings.INFOCLINICA_TIMEOUT_SECONDS
        ) as client:
            registration_payload = InfoClinicaRegistrationPayload(
                first_name=data.get("reg_firstName", ""),
                last_name=data.get("reg_lastName", ""),
                middle_name=data.get("reg_middleName"),
                birth_date=data.get("reg_birthDate"),
                email=data.get("reg_email", ""),
                phone=data.get("reg_phone", ""),
                snils=data.get("reg_snils", ""),
                gender=data.get("reg_gender"),
                accept=True,
                refuse_call=None,
                refuse_sms=None,
                confirmed="",
                check_data="",
                captcha=""
            )
            
            result = await client.registration(registration_payload)
            
            # Проверяем результат
            if result.status_code == 200:
                await context.set_state(None)
                await event.message.delete()
                await event.message.answer(
                    f'✅ Регистрация завершена!\n\n'
                    f'Фамилия: {data.get("reg_lastName")}\n'
                    f'Имя: {data.get("reg_firstName")}\n'
                    f'Отчество: {data.get("reg_middleName") or "не указано"}\n'
                    f'Дата рождения: {data.get("reg_birthDate")}\n'
                    f'Email: {data.get("reg_email")}\n'
                    f'Телефон: {data.get("reg_phone")}\n'
                    f'СНИЛС: {data.get("reg_snils")}\n'
                    f'Пол: {"Мужской" if data.get("reg_gender") == 1 else "Женский"}\n\n'
                    f'Запись подтверждена. Ожидайте подтверждения.'
                )
                await create_keyboard(event)
            else:
                error_msg = result.json.get('message', 'Ошибка регистрации') if result.json else 'Ошибка регистрации'
                await event.message.delete()
                await event.message.answer(
                    f'❌ Ошибка регистрации: {error_msg}\n\n'
                    f'Попробуйте еще раз или обратитесь в поддержку.'
                )
    except Exception as e:
        logging.error(f"Ошибка при регистрации: {e}")
        await event.message.delete()
        await event.message.answer(
            f'❌ Произошла ошибка при регистрации.\n\n'
            f'Попробуйте позже или обратитесь в поддержку.'
        )


@dp.message_callback(F.callback.payload == 'reject_personal_data')
async def handle_reject_personal_data(event: MessageCallback, context: MemoryContext):
    """Обработка отказа от обработки персональных данных"""
    await event.message.delete()
    await context.set_state(None)
    await event.message.answer(
        '❌ Регистрация отменена.\n\n'
        'Для создания записи необходимо согласие на обработку персональных данных.'
    )
    await create_keyboard(event)


@dp.message_callback(F.callback.payload == 'back_to_schedule')
async def handle_back_to_schedule(event: MessageCallback, context: MemoryContext):
    """Возврат к выбору даты (календарю)"""
    data = await context.get_data()
    branch_id = data.get('selected_branch_id')
    department_id = data.get('selected_department_id')
    doctor_id = data.get('selected_doctor_id')
    branches = data.get('branches_list', [])
    departments = data.get('departments_list', [])
    doctors = data.get('doctors_list', [])
    
    branch_name = "Филиал"
    for branch in branches:
        if str(branch.get("id")) == branch_id:
            branch_name = branch.get("name", "Филиал")
            break
    
    department_name = "Отделение"
    for department in departments:
        if str(department.get("id")) == department_id:
            department_name = department.get("name", "Отделение")
            break
    
    doctor_name = "Врач"
    doctor_dcode = data.get('selected_doctor_dcode')
    for doctor in doctors:
        if str(doctor.get("id")) == doctor_id or str(doctor.get("dcode")) == str(doctor_dcode):
            doctor_name = doctor.get("name", "Врач")
            break
    
    # Показываем календарь
    calendar_text, calendar_keyboard = create_calendar_keyboard(doctor_name, branch_name, department_name)
    
    await event.message.delete()
    await event.message.answer(
        text=calendar_text,
        attachments=[calendar_keyboard.as_markup()]
    )


async def main():
    await bot.set_my_commands(
        BotCommand(
            name='/start',
            description='Перезапустить бота'
        ),
        BotCommand(
            name='/clear',
            description='Очищает ваш контекст'
        ),
        BotCommand(
            name='/state',
            description='Показывают ваше контекстное состояние'
        ),
        BotCommand(
            name='/data',
            description='Показывает вашу контекстную память'
        ),
        BotCommand(
            name='/context',
            description='Показывают ваше контекстное состояние'
        )
    )
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
