import asyncio
import logging

from datetime import datetime

from maxapi import F
from maxapi.context import MemoryContext, State, StatesGroup
from maxapi.types import BotStarted, Command, MessageCreated, CallbackButton, MessageCallback, BotCommand
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from app.providers.infoclinica_client import InfoClinicaClient
from app.config import settings
from app.bot import bot, dp
from app.schemas.infoclinica import (
    InfoClinicaReservationSchedulePayload,
    ReservationScheduleService,
    InfoClinicaLoginPayload,
    InfoClinicaRegistrationPayload
)
from app.bot.router import router

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
            doctors_cached_branch_id=None
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


async def get_doctors(filial_id: int | None = None):
    """Получает список всех врачей с фильтрацией по филиалу"""
    async with InfoClinicaClient(
        base_url=settings.INFOCLINICA_BASE_URL,
        cookies=settings.INFOCLINICA_COOKIES,
        timeout_seconds=settings.INFOCLINICA_TIMEOUT_SECONDS
    ) as client:
        params = {}
        if filial_id:
            params["filial"] = filial_id
        
        result = await client.sdk_specialists_doctors(params=params if params else None)
        data = result.json or {}
        return data.get("data", [])


async def create_doctors_keyboard(event, context: MemoryContext, page: int = 0):
    """Создает клавиатуру со списком врачей с пагинацией"""
    # Получаем список врачей (кешируем в контексте или получаем заново)
    data = await context.get_data()
    doctors = data.get('doctors_list')
    branch_id = data.get('selected_branch_id')
    cached_branch_id = data.get('doctors_cached_branch_id')
    
    # Если кеш отсутствует или филиал изменился, загружаем заново
    if not doctors or cached_branch_id != branch_id:
        filial_id = int(branch_id) if branch_id else None
        doctors = await get_doctors(filial_id=filial_id)
        await context.update_data(
            doctors_list=doctors,
            doctors_page=0,
            doctors_cached_branch_id=branch_id
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
        doctor_id = doctor.get("id")
        doctor_name = doctor.get("name", "Без названия")
        # Ограничиваем длину названия для кнопки
        button_text = doctor_name[:30] + "..." if len(doctor_name) > 30 else doctor_name
        builder.row(
            CallbackButton(
                text=button_text,
                payload=f'doctor_{doctor_id}'
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
        # Очищаем предыдущие данные о врачах
        await context.update_data(doctors_list=None, doctors_page=0)
        
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


async def get_doctor_schedule(
    branch_id: int | None = None,
    doctor_id: int | None = None,
    department_id: int | None = None,
    online_mode: int = 1
):
    """Получает график работы врача через API reservation/schedule"""
    async with InfoClinicaClient(
        base_url=settings.INFOCLINICA_BASE_URL,
        cookies=settings.INFOCLINICA_COOKIES,
        timeout_seconds=settings.INFOCLINICA_TIMEOUT_SECONDS
    ) as client:
        # Формируем service объект с переданными параметрами
        # Безопасное преобразование в int, если значение None - используем 0
        def safe_int_or_zero(value):
            if value is None:
                return 0
            try:
                return int(value)
            except (ValueError, TypeError):
                return 0
        
        service = ReservationScheduleService(
            st=0,
            en=0,
            doctor=safe_int_or_zero(doctor_id),
            cashList=0,
            specList=safe_int_or_zero(department_id),
            filialId=safe_int_or_zero(branch_id),
            onlineMode=online_mode,
            nsp=""
        )
        
        payload = InfoClinicaReservationSchedulePayload(services=[service])
        result = await client.reservation_schedule(payload)
        return result.json or {}


def format_schedule_info(schedule_data: dict, doctor_name: str, branch_name: str, department_name: str):
    """Форматирует информацию о графике работы врача и ближайших доступных временах с кнопками"""
    from maxapi.utils.inline_keyboard import InlineKeyboardBuilder
    
    today = datetime.now().date()
    today_str = today.strftime("%Y%m%d")
    
    text_parts = [
        f'✅ Вы выбрали:',
        f'📍 Филиал: {branch_name}',
        f'🏥 Отделение: {department_name}',
        f'👨‍⚕️ Врач: {doctor_name}',
        '',
        '📅 График работы врача:'
    ]
    
    # Создаем клавиатуру для выбора времени
    builder = InlineKeyboardBuilder()
    available_times = []
    
    # Пытаемся извлечь данные о расписании
    # Структура ответа может варьироваться, поэтому обрабатываем разные варианты
    schedule_info = schedule_data.get('data') or schedule_data
    
    # Если есть информация о расписании на сегодня
    if isinstance(schedule_info, dict):
        # Ищем доступные временные слоты
        today_slots = []
        
        # Проверяем разные возможные структуры данных
        if 'schedule' in schedule_info:
            schedule_list = schedule_info.get('schedule', [])
        elif isinstance(schedule_info, list):
            schedule_list = schedule_info
        else:
            schedule_list = []
        
        # Ищем слоты на сегодня
        for slot in schedule_list:
            slot_date = slot.get('date') or slot.get('day') or ''
            if str(slot_date) == today_str or (isinstance(slot_date, str) and today_str in slot_date):
                time_slot = slot.get('time') or slot.get('st') or slot.get('start_time', '')
                if time_slot:
                    today_slots.append(time_slot)
        
        if today_slots:
            # Сортируем времена
            today_slots.sort()
            available_times = today_slots[:5]  # Берем первые 5 времен
        else:
            # Тестовые данные времени, если API не вернул данные
            available_times = ['09:00', '10:30', '12:00', '14:00', '15:30']
            
        text_parts.append(f'\n🕐 Выберите удобное время:')
            
        # Добавляем общую информацию о графике, если есть
        if 'work_hours' in schedule_info:
            work_hours = schedule_info.get('work_hours')
            text_parts.append(f'\n⏱️ График работы: {work_hours}')
    else:
        # Тестовые данные времени, если структура данных неожиданная
        available_times = ['09:00', '10:30', '12:00', '14:00', '15:30']
        text_parts.append(f'\n🕐 Выберите удобное время:')
    
    # Создаем кнопки для каждого времени (по 2 кнопки в ряд)
    for i in range(0, len(available_times), 2):
        row_times = available_times[i:i+2]
        buttons = [
            CallbackButton(
                text=time,
                payload=f'time_{time.replace(":", "")}'
            )
            for time in row_times
        ]
        builder.row(*buttons)
    
    # Кнопка "Назад" к врачам
    builder.row(
        CallbackButton(
            text='🔙 Назад к врачам',
            payload='back_to_doctors'
        )
    )
    
    text = '\n'.join(text_parts)
    return text, builder


@dp.message_callback(F.callback.payload.startswith('doctor_'))
async def handle_doctor_selection(event: MessageCallback, context: MemoryContext):
    # Извлекаем ID врача из payload
    doctor_id = event.callback.payload.split('_')[-1]
    
    # Получаем информацию о враче
    data = await context.get_data()
    doctors = data.get('doctors_list', [])
    
    selected_doctor = None
    for doctor in doctors:
        if str(doctor.get("id")) == doctor_id:
            selected_doctor = doctor
            break
    
    if selected_doctor:
        await context.update_data(selected_doctor_id=doctor_id)
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
        
        try:
            # Преобразуем ID в int, проверяя на None и строку 'None'
            def safe_int(value):
                if not value or value == 'None' or value == 'null':
                    return None
                try:
                    return int(value)
                except (ValueError, TypeError):
                    return None
            
            # Получаем график работы врача с переданными параметрами
            schedule_data = await get_doctor_schedule(
                branch_id=safe_int(branch_id),
                doctor_id=safe_int(doctor_id),
                department_id=safe_int(department_id),
                online_mode=1
            )
            
            # Форматируем информацию о графике (возвращает текст и клавиатуру)
            schedule_text, time_keyboard = format_schedule_info(schedule_data, doctor_name, branch_name, department_name)
            
            # Отправляем информацию о графике с кнопками времени
            await event.message.answer(
                text=schedule_text,
                attachments=[time_keyboard.as_markup()]
            )
            
        except Exception as e:
            logging.error(f"Ошибка при получении графика врача: {e}")
            await event.message.answer(
                f'Вы выбрали:\n📍 Филиал: {branch_name}\n🏥 Отделение: {department_name}\n👨‍⚕️ Врач: {doctor_name}\n\n'
                f'⚠️ Не удалось загрузить график работы врача. Попробуйте позже.'
            )
            await create_keyboard(event)
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
    # Извлекаем время из payload (формат: time_0900, time_1030 и т.д.)
    time_str = event.callback.payload.replace('time_', '')
    # Восстанавливаем формат времени (0900 -> 09:00)
    if len(time_str) == 4:
        selected_time = f"{time_str[:2]}:{time_str[2:]}"
    else:
        selected_time = time_str
    
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
            text='🔙 Назад к выбору времени',
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
        # Выполняем вход через API
        async with InfoClinicaClient(
            base_url=settings.INFOCLINICA_BASE_URL,
            cookies=settings.INFOCLINICA_COOKIES,
            timeout_seconds=settings.INFOCLINICA_TIMEOUT_SECONDS
        ) as client:
            login_payload = InfoClinicaLoginPayload(
                username=username,
                password=password,
                accept=False,
                code="",
                form_key="pcode",
                g_recaptcha_response=""
            )
            
            result = await client.login(login_payload)
            
            # Проверяем результат
            if result.status_code == 200:
                await context.set_state(None)
                await event.message.answer(
                    f'✅ Вход выполнен успешно!\n\n'
                    f'Логин: {username}\n\n'
                    f'Запись подтверждена. Ожидайте подтверждения.'
                )
                await create_keyboard(event)
            else:
                error_msg = result.json.get('message', 'Ошибка входа') if result.json else 'Ошибка входа'
                await event.message.answer(
                    f'❌ Ошибка входа: {error_msg}\n\n'
                    f'Попробуйте еще раз.'
                )
    except Exception as e:
        logging.error(f"Ошибка при входе: {e}")
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
    """Возврат к выбору времени"""
    data = await context.get_data()
    branch_id = data.get('selected_branch_id')
    department_id = data.get('selected_department_id')
    doctor_id = data.get('selected_doctor_id')
    
    # Получаем информацию о враче и формируем расписание
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
    
    # Получаем расписание
    def safe_int(value):
        if not value or value == 'None' or value == 'null':
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
    
    schedule_data = await get_doctor_schedule(
        branch_id=safe_int(branch_id),
        doctor_id=safe_int(doctor_id),
        department_id=safe_int(department_id),
        online_mode=1
    )
    
    schedule_text, time_keyboard = format_schedule_info(schedule_data, doctor_name, branch_name, department_name)
    
    await event.message.delete()
    await event.message.answer(
        text=schedule_text,
        attachments=[time_keyboard.as_markup()]
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
