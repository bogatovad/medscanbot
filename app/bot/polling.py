import asyncio
import logging
import tempfile
import os

from datetime import datetime, timedelta, date

import httpx

from maxapi import F
from maxapi.context import MemoryContext, State, StatesGroup
from maxapi.enums.attachment import AttachmentType
from maxapi.types import (
    BotStarted,
    Command,
    MessageCreated,
    CallbackButton,
    MessageCallback,
    BotCommand,
    InputMedia,
    Attachment,
    ButtonsPayload,
    RequestContactButton,
    Message,
)
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from app.providers.max_api import MaxApiClient
from app.workers.max_api import poll_max_api_status
from app.providers.infoclinica_client import InfoClinicaClient
from app.config import settings
from app.bot import bot, dp
from app.db.base import DatabaseSessionManager
from app.crud.registered_user import RegisteredUserRepository
from app.schemas.infoclinica import CreatePatientPayload, UpdatePatientCredentialsPayload
from app.schemas.infoclinica import (
    InfoClinicaRegistrationPayload,
    InfoClinicaReservationReservePayload,
)
from app.bot.router import router

logging.basicConfig(level=logging.INFO)
dp.include_routers(router)

start_text = '''Чат-бота Medscan 💙'''

BRANCHES_PER_PAGE = 5
DEPARTMENTS_PER_PAGE = 5
DOCTORS_PER_PAGE = 5


async def download_image_to_temp(url: str) -> str | None:
    """
    Скачивает изображение по URL во временный файл и возвращает путь к нему.
    
    Args:
        url: URL изображения
        
    Returns:
        str: Путь к временному файлу или None в случае ошибки
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            
            # Определяем расширение файла из URL или Content-Type
            ext = ".jpg"
            if "png" in url.lower() or response.headers.get("content-type", "").startswith("image/png"):
                ext = ".png"
            elif "gif" in url.lower() or response.headers.get("content-type", "").startswith("image/gif"):
                ext = ".gif"
            
            # Создаем временный файл
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_file:
                tmp_file.write(response.content)
                return tmp_file.name
    except Exception as e:
        logging.error(f"Ошибка при скачивании изображения {url}: {e}")
        return None


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


class LkRegistrationForm(StatesGroup):
    """Форма регистрации в ЛК: ввод всех данных одним сообщением (6 строк)"""
    data = State()


class LkChangeCredentialsForm(StatesGroup):
    """Форма смены логина и пароля: две строки — email, пароль (в МИС меняются только они)."""
    data = State()


class AuthForm(StatesGroup):
    """Форма авторизации: две строки — логин (email), пароль."""
    data = State()


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


async def _delete_messages(event, context: MemoryContext):
    """Удаляет все сообщения, сохраненные в контексте под ключом delete_messages_id."""
    try:
        data = await context.get_data()
        delete_messages_id = data.get('delete_messages_id', [])

        if delete_messages_id:
            # Если это список, обрабатываем каждый элемент
            if isinstance(delete_messages_id, list):
                for msg_id in delete_messages_id:
                    try:
                        await bot.delete_message(message_id=msg_id)
                    except Exception as e:
                        logging.warning(f"Не удалось удалить сообщение {msg_id}: {e}")
            else:
                # Если это не список, а одно значение, обрабатываем как одно сообщение
                try:
                    await bot.delete_message(message_id=delete_messages_id)
                except Exception as e:
                    logging.warning(f"Не удалось удалить сообщение {delete_messages_id}: {e}")
            # Очищаем список ID сообщений из контекста
            data['delete_messages_id'] = []
            await context.set_data(data)
    except Exception as e:
        logging.debug(f"Ошибка при удалении сообщений: {e}")


def _build_main_keyboard_buttons(is_registered: bool):
    """Собирает ряды кнопок главного меню. Регистрация или Личный кабинет в зависимости от is_registered."""
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text='📅 Текущие записи',
            payload='btn_current_appointment'
        )
    )
    builder.row(
        CallbackButton(
            text='➕ Записаться на прием',
            payload='btn_make_appointment'
        )
    )
    if is_registered:
        builder.row(
            CallbackButton(
                text='👤 Личный кабинет',
                payload='btn_personal_cabinet'
            )
        )
    else:
        builder.row(
            CallbackButton(
                text='📝 Регистрация',
                payload='btn_lk_registration'
            )
        )
    # builder.row(
    #     CallbackButton(
    #         text='✍️ Подписать документы онлайн',
    #         payload='btn_sign_documents'
    #     )
    # )
    # Добавляем кнопку авторизации, если включена в конфиге
    if settings.enable_auth:
        builder.row(
            CallbackButton(
                text='🔐 Авторизация',
                payload='btn_auth'
            )
        )
    builder.row(
        CallbackButton(
            text='ℹ️ Информация о Медскан',
            payload='btn_info'
        )
    )
    return builder


@dp.message_created(Command('start'))
async def handle_start_command(event: MessageCreated, context: MemoryContext):
    id_max = context.user_id
    is_registered = False
    dsm = DatabaseSessionManager.create(settings.DB_URL)
    async with dsm.get_session() as session:
        repo = RegisteredUserRepository(session)
        user = await repo.get_by_max_id(id_max)
        is_registered = user is not None
    builder = _build_main_keyboard_buttons(is_registered)
    await event.message.answer(
        text=start_text,
        attachments=[
            builder.as_markup(),
        ]
    )


async def create_keyboard(event, context):
    id_max = context.user_id
    is_registered = False
    dsm = DatabaseSessionManager.create(settings.DB_URL)
    async with dsm.get_session() as session:
        repo = RegisteredUserRepository(session)
        user = await repo.get_by_max_id(id_max)
        is_registered = user is not None
    builder = _build_main_keyboard_buttons(is_registered)
    await event.message.answer(
        text=start_text,
        attachments=[
            builder.as_markup(),
        ]
    )


# --- Регистрация в ЛК (одним сообщением) ---

REGISTRATION_INSTRUCTIONS = """📝 Регистрация в личный кабинет

Введите данные **одним сообщением**, каждое значение с новой строки (всего 6 строк):

1️⃣ Фамилия
2️⃣ Имя  
3️⃣ Отчество
4️⃣ Дата рождения (формат ГГГГ-ММ-ДД, например 1990-01-15)
5️⃣ Email (логин в ЛК)
6️⃣ Пароль

Пример:
Иванов
Иван
Иванович
1990-01-15
ivanov@example.com
мой_пароль123"""


def parse_lk_registration_text(text: str) -> dict | None:
    """
    Парсит сообщение из 6 строк в словарь для API.
    Возвращает None при ошибке формата или даты.
    """
    lines = [line.strip() for line in (text or "").strip().split("\n") if line.strip()]
    if len(lines) < 6:
        return None
    lastname, firstname, midname, bdate_str, cllogin, clpassword = lines[0], lines[1], lines[2], lines[3], lines[4], lines[5]
    # Проверка даты ГГГГ-ММ-ДД
    try:
        datetime.strptime(bdate_str, "%Y-%m-%d")
    except ValueError:
        return None
    return {
        "lastname": lastname,
        "firstname": firstname,
        "midname": midname,
        "bdate": bdate_str,
        "cllogin": cllogin,
        "clpassword": clpassword,
    }


@dp.message_callback(F.callback.payload == 'btn_personal_cabinet')
async def handle_personal_cabinet(event: MessageCallback, context: MemoryContext):
    """Кнопка «Личный кабинет» — показываем данные из БД и дату регистрации."""
    await event.message.delete()
    # Удаляем все сообщения, сохраненные для удаления
    await _delete_messages(event, context)
    id_max = context.user_id
    logging.info(f"DSKLFGJNSDLKJFNSDKLJN!! {id_max=}")
    dsm = DatabaseSessionManager.create(settings.DB_URL)
    async with dsm.get_session() as session:
        repo = RegisteredUserRepository(session)
        user = await repo.get_by_max_id(id_max)
    if not user:
        await event.message.answer("Пользователь не найден. Нажмите /start.")
        await create_keyboard(event, context)
        return
    reg_date = user.registered_at
    if reg_date and hasattr(reg_date, "strftime"):
        reg_str = reg_date.strftime("%d.%m.%Y %H:%M")
    else:
        reg_str = str(reg_date)
    text = (
        "👤 Личный кабинет\n\n"
        f"Фамилия: {user.lastname}\n"
        f"Имя: {user.firstname}\n"
        f"Отчество: {user.midname or '—'}\n"
        f"Дата рождения: {user.bdate}\n"
        f"Логин (email): {user.cllogin}\n"
        f"Пароль: {user.clpassword}\n"
        f"Код пациента (ИК): {user.pcode}\n\n"
        f"📅 Дата регистрации в системе: {reg_str}"
    )
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text='🔙 Назад', payload='back_to_main')
    )
    builder.row(
        CallbackButton(text='🔐 Поменять логин и пароль', payload='btn_change_credentials')
    )
    builder.row(
        CallbackButton(text='🗑 Удалить аккаунт', payload='btn_delete_account')
    )
    await event.message.answer(text=text, attachments=[builder.as_markup()])


@dp.message_callback(F.callback.payload == 'btn_change_credentials')
async def handle_change_credentials_button(event: MessageCallback, context: MemoryContext):
    """Кнопка «Поменять логин и пароль» — запрашиваем email и пароль (2 строки), обновляем БД и МИС."""
    await event.message.delete()
    await context.set_state(LkChangeCredentialsForm.data)
    await event.message.answer(
        "🔐 Смена логина и пароля.\n\n"
        "Отправьте двумя строками:\n"
        "1. Новый email (логин)\n"
        "2. Новый пароль"
    )


def _parse_login_password(text: str) -> tuple[str, str] | None:
    """Парсит 2 строки: логин, пароль. Возвращает (login, password) или None."""
    lines = [line.strip() for line in (text or "").strip().split("\n") if line.strip()]
    if len(lines) < 2:
        return None
    return lines[0], lines[1]


@dp.message_created(F.message.body.text, LkChangeCredentialsForm.data)
async def handle_change_credentials_data(event: MessageCreated, context: MemoryContext):
    """Введены логин и пароль — обновляем cllogin в БД и отправляем оба значения в МИС (PUT credentials)."""
    await context.set_state(None)
    parsed = _parse_login_password((event.message.body.text or "").strip())
    if not parsed:
        await event.message.answer("Нужны две строки: email и пароль. Попробуйте снова.")
        return
    new_login, new_password = parsed
    if not new_login or not new_password:
        await event.message.answer("Логин и пароль не должны быть пустыми. Попробуйте снова.")
        return
    id_max = context.user_id
    try:
        dsm = DatabaseSessionManager.create(settings.DB_URL)
        async with dsm.get_session() as session:
            repo = RegisteredUserRepository(session)
            user = await repo.get_by_max_id(id_max)
            if not user:
                await event.message.answer("Пользователь не найден.")
                await create_keyboard(event, context)
                return
            pcode = str(user.pcode)
            await repo.update(id_max, cllogin=new_login, clpassword=new_password)
            await session.commit()

        creds = UpdatePatientCredentialsPayload(cllogin=new_login, clpassword=new_password)
        async with InfoClinicaClient() as client:
            result = await client.update_patient_credentials(pcode, creds)
        if result.status_code in (200, 204):
            await event.message.answer("✅ Логин и пароль обновлены в боте и в системе МИС.")
        else:
            err = (result.json or {}).get("message") if isinstance(result.json, dict) else result.text or "Ошибка МИС"
            await event.message.answer(f"✅ Данные обновлены в боте.\n⚠️ В МИС: {err}")
        await create_keyboard(event, context)
    except Exception as e:
        logging.exception("Ошибка при смене логина и пароля")
        await event.message.answer(f"❌ Ошибка: {str(e)[:200]}")
        await create_keyboard(event, context)


@dp.message_callback(F.callback.payload == 'btn_delete_account')
async def handle_delete_account(event: MessageCallback, context: MemoryContext):
    """Удаление аккаунта из БД по кнопке «Удалить аккаунт» в личном кабинете."""
    await event.message.delete()
    id_max = context.user_id
    dsm = DatabaseSessionManager.create(settings.DB_URL)
    async with dsm.get_session() as session:
        repo = RegisteredUserRepository(session)
        deleted = await repo.delete_by_max_id(id_max)
        if deleted:
            await session.commit()
    if deleted:
        await event.message.answer("✅ Аккаунт удалён. Вы можете зарегистрироваться снова.")
    else:
        await event.message.answer("Аккаунт не найден или уже удалён.")
    await create_keyboard(event, context)


@dp.message_callback(F.callback.payload == 'btn_lk_registration')
async def handle_lk_registration_button(event: MessageCallback, context: MemoryContext):
    """Кнопка «Регистрация» — запрашиваем данные одним сообщением."""
    await event.message.delete()
    # Удаляем все сообщения, сохраненные для удаления
    await _delete_messages(event, context)
    await context.set_state(LkRegistrationForm.data)
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text='🔙 Назад', payload='back_to_main')
    )
    await event.message.answer(
        text=REGISTRATION_INSTRUCTIONS,
        attachments=[builder.as_markup()]
    )


@dp.message_created(F.message.body.text, LkRegistrationForm.data)
async def handle_lk_registration_data(event: MessageCreated, context: MemoryContext):
    """Обработка введённых данных регистрации ЛК: запрос в МИС (createPatients) и сохранение в БД."""
    text = (event.message.body.text or "").strip()
    payload = parse_lk_registration_text(text)

    if payload is None:
        await event.message.answer(
            "❌ Неверный формат. Нужно 6 строк: Фамилия, Имя, Отчество, Дата (ГГГГ-ММ-ДД), Email, Пароль.\n\nПопробуйте ещё раз или нажмите /start для отмены."
        )
        return

    await context.set_state(None)

    id_max = context.user_id

    try:
        create_payload = CreatePatientPayload(
            lastname=payload["lastname"],
            firstname=payload["firstname"],
            midname=payload["midname"],
            bdate=payload["bdate"],
            cllogin=payload["cllogin"],
            clpassword=payload["clpassword"],
        )
        async with InfoClinicaClient() as client:
            result = await client.create_patient(create_payload)

        if result.status_code not in (200, 201):
            err = (result.json or {}).get("message") if isinstance(result.json, dict) else result.text or "Ошибка регистрации в МИС"
            await event.message.answer(f"❌ Регистрация в системе не удалась: {err}")
            return

        pcode = None
        if result.json:
            if isinstance(result.json, dict):
                pcode = result.json.get("pcode")
            elif isinstance(result.json, str):
                pcode = result.json
        if not pcode:
            await event.message.answer("❌ В ответе системы не найден идентификатор пациента (pcode).")
            return

        dsm = DatabaseSessionManager.create(settings.DB_URL)
        async with dsm.get_session() as session:
            repo = RegisteredUserRepository(session)
            await repo.save(
                id_max=id_max,
                pcode=str(pcode),
                lastname=payload["lastname"],
                firstname=payload["firstname"],
                midname=payload["midname"] or None,
                bdate=payload["bdate"],
                cllogin=payload["cllogin"],
                clpassword=payload["clpassword"],
            )
            await session.commit()

        await event.message.answer(
            "✅ Регистрация в личном кабинете завершена. Данные сохранены в системе."
        )
        await create_keyboard(event, context)
    except httpx.ConnectTimeout:
        logging.warning("Таймаут соединения с API регистрации пациентов (МИС)")
        await event.message.answer(
            "❌ Сервис регистрации временно недоступен (таймаут соединения).\n\n"
            "Сервер МИС не ответил вовремя. Проверьте доступность сервера или попробуйте позже."
        )
    except httpx.ConnectError as e:
        logging.warning("Ошибка соединения с API регистрации пациентов: %s", e)
        await event.message.answer(
            "❌ Не удалось подключиться к сервису регистрации (сервер МИС недоступен).\n\n"
            "Попробуйте позже или обратитесь в поддержку."
        )
    except Exception as e:
        logging.exception("Ошибка при регистрации в ЛК")
        await event.message.answer(
            f"❌ Произошла ошибка при регистрации. Попробуйте позже или обратитесь в поддержку.\n{str(e)[:200]}"
        )


# --- Авторизация ---

@dp.message_callback(F.callback.payload == 'btn_auth')
async def handle_auth_button(event: MessageCallback, context: MemoryContext):
    """Кнопка «Авторизация» — запрашиваем логин и пароль (2 строки)."""
    await event.message.delete()
    # Удаляем все сообщения, сохраненные для удаления
    await _delete_messages(event, context)
    await context.set_state(AuthForm.data)
    await event.message.answer(
        "🔐 Авторизация\n\n"
        "Отправьте двумя строками:\n"
        "1. Email (логин)\n"
        "2. Пароль"
    )


@dp.message_created(F.message.body.text, AuthForm.data)
async def handle_auth_data(event: MessageCreated, context: MemoryContext):
    """Введены логин и пароль — проверяем их в БД."""
    await context.set_state(None)
    parsed = _parse_login_password((event.message.body.text or "").strip())
    if not parsed:
        await event.message.answer("Нужны две строки: email и пароль. Попробуйте снова.")
        return
    
    login, password = parsed
    if not login or not password:
        await event.message.answer("Логин и пароль не должны быть пустыми. Попробуйте снова.")
        return
    
    id_max = context.user_id
    try:
        dsm = DatabaseSessionManager.create(settings.DB_URL)
        async with dsm.get_session() as session:
            repo = RegisteredUserRepository(session)
            # Ищем пользователя по логину и паролю
            user = await repo.get_by_login_and_password(login, password)
            
            if user:
                # Если пользователь найден, проверяем его текущий id_max
                if user.id_max == id_max:
                    # Пользователь уже привязан к этому id_max
                    await event.message.answer("✅ Вы уже авторизованы с этими данными.")
                    await create_keyboard(event, context)
                    return
                elif user.id_max != id_max:
                    # Аккаунт уже привязан к другому пользователю бота
                    # Проверяем, не занят ли текущий id_max другим пользователем
                    existing_user = await repo.get_by_max_id(id_max)
                    if existing_user and existing_user.id != user.id:
                        await event.message.answer(
                            "❌ Ваш текущий аккаунт в боте уже привязан к другому пользователю. "
                            "Удалите текущую привязку или используйте другой аккаунт."
                        )
                        await create_keyboard(event, context)
                        return
                    # Перепривязываем аккаунт к текущему id_max
                    user.id_max = id_max
                    await session.commit()
                    await event.message.answer(
                        "✅ Авторизация успешна! Аккаунт перепривязан к вашему пользователю в боте."
                    )
                    await create_keyboard(event, context)
                    return
            else:
                await event.message.answer(
                    "❌ Неверный логин или пароль. Проверьте введенные данные и попробуйте снова."
                )
                await create_keyboard(event, context)
    except Exception as e:
        logging.exception("Ошибка при авторизации")
        await event.message.answer(f"❌ Ошибка: {str(e)[:200]}")
        await create_keyboard(event, context)


@dp.message_callback(F.callback.payload == 'btn_info')
async def handle_info_button(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    # Удаляем все сообщения, сохраненные для удаления
    await _delete_messages(event, context)
    
    info_text = (
        'АО «Медскан» – динамично развивающаяся группа компаний и один из лидеров '
        'негосударственного сектора здравоохранения в России. Медицинские '
        'учреждения холдинга предлагают полный спектр высокотехнологичной '
        'медицинской помощи по передовым мировым протоколам'
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text='1. Миссия и ценности',
            payload='info_mission'
        )
    )
    builder.row(
        CallbackButton(
            text='2. Организации',
            payload='info_organizations'
        )
    )
    builder.row(
        CallbackButton(
            text='3. Контакты',
            payload='info_contacts'
        )
    )
    builder.row(
        CallbackButton(
            text='🔙 Назад',
            payload='back_to_main'
        )
    )
    
    await event.message.answer(
        text=info_text,
        attachments=[builder.as_markup()]
    )


@dp.message_callback(F.callback.payload == 'info_mission')
async def handle_info_mission(event: MessageCallback, context: MemoryContext):
    """Обработчик кнопки 'Миссия и ценности'"""
    await event.message.delete()
    
    mission_text = (
        'Согласно статье 7 Конституции, «Российская Федерация - социальное государство, '
        'политика которого направлена на создание условий, обеспечивающих достойную жизнь '
        'и свободное развитие человека». Федеральный закон «Об основах охраны здоровья граждан» определяет '
        'здоровье как «состояние физического, психического и социального благополучия человека». \n\n'
        ' Мы понимаем социальную ответственность бизнеса как отказ от эксплуатации человеческого '
        'капитала в пользу инвестиций в раскрытие его потенциала. Высшая ценность для нас - '
        'человек и качество его жизни, важнейшей составляющей которого является здоровье. '
        'Здравоохранение – не просто отрасль из сферы услуг, оказывающая помощь людям, '
        'испытывающим проблемы со своим здоровьем и занимающаяся их реабилитацией после '
        'выздоровления. Это система, выступающая гарантом социального благополучия. '
        'Медицина должна не только лечить болезнь, но и работать на опережение,'
        ' предотвращая угрозы здоровью, сберегая ресурсы общества \n\n'
        'Поэтому мы рассматриваем свою деятельность как социальный проект и гуманитарную миссию, '
        'осуществляемую в соответствии с законами Российской Федерации и в парадигме '
        'глобальных целей устойчивого развития. Для решения этих задач мы реализуем '
        'стратегию по созданию действительно народной медицинской компании,'
        ' оказывающей высококвалифицированную помощь миллионам пациентов во всех '
        'регионах нашей огромной страны, в государствах Евразийского Экономического '
        'Союза и Содружества Независимых Государств. Формирование широкой сети учреждений '
        'здравоохранения позволит внедрить единые стандарты, обеспечить обмен знаниями и опытом. Мы руководствуемся '
        'принципами корпоративного управления, ориентирующими бизнес на решение социальных и '
        'экологических проблем. Медицина - это высокотехнологичная сфера, которая обеспечивает '
        'рабочие места не только в лечебных учреждениях, но и смежных отраслях. Медицинское '
        'учреждение – это, прежде всего, люди, которые в нем работают'
    )
    
    builder = InlineKeyboardBuilder()
 
    builder.row(
        CallbackButton(
            text='🔙 Назад',
            payload='btn_info'
        )
    )
    
    # Добавление изображения
    attachments = [builder.as_markup()]
    
    image_url = "static/image/info_mission.png"

    photo = InputMedia(path=image_url)
    attachments.insert(0, photo)
    
    await event.message.answer(
        text=mission_text,
        attachments=attachments
    )


@dp.message_callback(F.callback.payload == 'info_organizations')
async def handle_info_organizations(event: MessageCallback, context: MemoryContext):
    """Обработчик кнопки 'Организации'"""
    await event.message.delete()
    
    organizations_text = 'Выберите организацию:'
    
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text='1. Хадасса',
            payload='info_hadassah'
        )
    )
    builder.row(
        CallbackButton(
            text='2. Яуза',
            payload='info_yauza'
        )
    )
    builder.row(
        CallbackButton(
            text='3. ООО Медскан',
            payload='info_medscan_llc'
        )
    )
    builder.row(
        CallbackButton(
            text='4. Медасист Курск',
            payload='info_medassist_kursk'
        )
    )
    builder.row(
        CallbackButton(
            text='5. Медикал он Групп',
            payload='info_medical_on_group'
        )
    )
    builder.row(
        CallbackButton(
            text='6. KDL',
            payload='info_kdl'
        )
    )
    builder.row(
        CallbackButton(
            text='🔙 Назад',
            payload='btn_info'
        )
    )
    
    await event.message.answer(
        text=organizations_text,
        attachments=[builder.as_markup()]
    )


@dp.message_callback(F.callback.payload == 'info_hadassah')
async def handle_info_hadassah(event: MessageCallback, context: MemoryContext):
    """Обработчик кнопки 'Хадасса'"""
    await event.message.delete()
    
    hadassah_text = (
        'МЕЖДУНАРОДНЫЙ МЕДИЦИНСКИЙ ХАБ\n'
        'Лучшие мировые и Российские практики, передовые технологии и научные разработки для поддержания здоровья всей семьи на каждом этапе жизни. Доступ к инновациям и незарегистрированным в РФ методам лечения под наблюдением международной команды врачей.\n\n'
        'Мы лечим не болезни, а человека. мы создаём новую культуру — культуру здоровья, доверия и безусловной безопасности.\n'
        'Для нас важно не просто поставить диагноз, а окружить вас заботой на каждом шагу. Я руковожу международной командой врачей мирового уровня, и я лично ручаюсь за то, что каждый протокол лечения, каждая деталь в клинике — от оборудования до общения — подчинены одной цели: вашему спокойствию и уверенности в завтрашнем дне. Так рождается медицина будущего — умная, чуткая и по-настоящему гуманная. Добро пожаловать в «Медскан Hadassah».\n'
        'Борис Тамазович Чурадзе\n'
        'Руководитель / Главный врач клиники Медскан Хадасса\n\n'
        'Адрес: Инновационный центр Сколково, Москва\n'
        'Большой бульвар, 46с1\n'
        'Сайт: https://hadassah.moscow/\n'
        'Телефон: +7 (495) 186-41-32'
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text='🔙 Назад',
            payload='info_organizations'
        )
    )
    
    attachments = [builder.as_markup()]

    image_url = "static/image/hadassah.jpeg"

    photo = InputMedia(path=image_url)
    attachments.insert(0, photo)
    
    await event.message.answer(
        text=hadassah_text,
        attachments=attachments
    )


@dp.message_callback(F.callback.payload == 'info_yauza')
async def handle_info_yauza(event: MessageCallback, context: MemoryContext):
    """Обработчик кнопки 'Яуза'"""
    await event.message.delete()
    
    yauza_text = (
        'Добро пожаловать в Госпиталь «Медскан» на Яузе!\n\n'
        'Здоровье — самая ценная часть нашей жизни. В «Медскан» мы не просто лечим заболевания, мы заботимся о каждом человеке, кто переступает порог нашего госпиталя. Благодаря современным технологиям и индивидуальному подходу, мы создаём условия, в которых лечение становится максимально эффективным и комфортным.\n\n'
        'Каждый из вас для нас — не просто пациент, а уникальная история, за которой стоит семья, мечты и планы на будущее. Мы гордимся доверием, которое вы оказываете нам, и считаем своей главной задачей оправдывать его каждый день.\n'
        'Спасибо, что выбираете «Медскан». Мы рядом, когда вам нужна поддержка, и готовы идти вместе к здоровому и счастливому будущему.\n\n'
        'Будьте здоровы и счастливы!\n\n'
        'Подтетенев Дмитрий Сергеевич\n'
        'Генеральный директор Госпиталя Медскан на Яузе\n\n'
        'Адрес: Москва, ул. Волочаевская, д.15, к.1\n'
        'Сайт: https://www.yamed.ru/\n'
        'Телефон: +7 (495) 126-81-50'
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text='🔙 Назад',
            payload='info_organizations'
        )
    )
    
    # Добавление изображения
    attachments = [builder.as_markup()]

    image_url = "static/image/yauza.jpeg"

    photo = InputMedia(path=image_url)
    attachments.insert(0, photo)

    await event.message.answer(
        text=yauza_text,
        attachments=attachments
    )
    

@dp.message_callback(F.callback.payload == 'info_medscan_llc')
async def handle_info_medscan_llc(event: MessageCallback, context: MemoryContext):
    """Обработчик кнопки 'ООО Медскан'"""
    await event.message.delete()
    
    medscan_llc_text = (
        'Медскан — динамично развивающаяся сеть современных медицинских центров с широким спектром высокотехнологичных методов диагностики и лечения по следующим направлениям:\n'
        'Онкологический центр: лечении онкологических заболеваний с использованием лучевой и лекарственной терапии.\n'
        'Лучевая диагностика: МРТ, КТ, УЗИ, рентген, маммография.\n'
        'Лабораторная диагностика: все виды лабораторных исследований.'
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text='🔙 Назад',
            payload='info_organizations'
        )
    )
    
    # Добавление изображения
    attachments = [builder.as_markup()]

    image_url = "static/image/medscan_llc.jpeg"

    photo = InputMedia(path=image_url)
    attachments.insert(0, photo)

    await event.message.answer(
        text=medscan_llc_text,
        attachments=attachments
    )
    

@dp.message_callback(F.callback.payload == 'info_medassist_kursk')
async def handle_info_medassist_kursk(event: MessageCallback, context: MemoryContext):
    """Обработчик кнопки 'Медасист Курск'"""
    await event.message.delete()
    
    medassist_kursk_text = (
        'Медицинский центр «Медассист» – это:\n'
        'комплексный подход к диагностике и лечению;\n'
        'многопрофильный хирургический стационар;\n'
        'профессионализм всех сотрудников;\n'
        'современное оборудование экспертного класса;\n'
        'оказание платных медицинских услуг, а также оказание медицинских услуг в рамках территориальной программы обязательного медицинского страхования;\n'
        'работа с программами добровольного медицинского страхования;\n'
        'программы лояльности для клиентов;\n'
        'расположение в центре города;\n'
        'современное здание, адаптированное для посещения пациентов с ограниченными возможностями.\n\n'
        'С момента основания и до сегодняшнего дня медицинский центр «Медассист» - ведущее частное лечебное учреждение в городе. Здесь оказывают профессиональную медицинскую помощь взрослым и детям. Полный перечень наших услуг состоит из более чем 2000 видов услуг по 120 направлениям. Это и амбулаторные приемы опытных специалистов с многолетним стажем работы, и современное диагностическое отделение высокого качества, и дневной, и круглосуточный стационар с отдельными палатами, и, конечно, оборудованный по европейским стандартам операционный блок. К нам обращаются за лечением пациенты не только из нашего региона, но и всей России: Москвы и Московской области, Брянской, Орловской, Воронежской, Белгородской и многих других областей.\n\n'
        'Адрес: г. Курск, ул. Димитрова, 16\n'
        'Телефон: +7 (4712) 46-03-03\n'
        'Сайт: https://medassist-k.ru/'
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text='🔙 Назад',
            payload='info_organizations'
        )
    )
    
    # Добавление изображения
    attachments = [builder.as_markup()]

    image_url = "static/image/medassist_kursk.jpeg"

    photo = InputMedia(path=image_url)
    attachments.insert(0, photo)
    
    await event.message.answer(
        text=medassist_kursk_text,
        attachments=attachments
    )
    

@dp.message_callback(F.callback.payload == 'info_medical_on_group')
async def handle_info_medical_on_group(event: MessageCallback, context: MemoryContext):
    """Обработчик кнопки 'Медикал он Групп'"""
    await event.message.delete()
    
    medical_on_group_text = (
        'Medical On Group - ведущая частная международная компания в области решения деликатных медицинских проблем, ориентированная на эффективность лечения. Правильно поставленный много лет назад акцент на качество и доступность оказываемых пациенту услуг остается определяющим в деятельности корпорации и по сей день.\n\n'
        'Основные ценности в работе:\n'
        'Развитие и совершенствование медицины\n'
        'Понимание пациента и ответственность перед ним\n'
        'Повышение качества жизни общества\n'
        'Результат - сверх ожидания пациента\n'
        'Долгосрочные отношения с партнерами и сотрудниками\n'
        'Новая культура здоровья\n\n'
        'Телефон: 8 (812) 325-55-55\n'
        'Сайт: https://medongroup.ru/'
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text='🔙 Назад',
            payload='info_organizations'
        )
    )
    
    # Добавление изображения
    attachments = [builder.as_markup()]

    image_url = "static/image/medical_on_group.png"

    photo = InputMedia(path=image_url)
    attachments.insert(0, photo)

    await event.message.answer(
        text=medical_on_group_text,
        attachments=attachments
    )
    

@dp.message_callback(F.callback.payload == 'info_kdl')
async def handle_info_kdl(event: MessageCallback, context: MemoryContext):
    """Обработчик кнопки 'KDL'"""
    await event.message.delete()
    
    kdl_text = (
        'Контент:\n'
        'К:\n'
        'Улучшаем качество жизни, повышая культуру заботы о себе\n\n'
        'KDL — независимая федеральная сеть медицинских лабораторий, специализирующаяся исключительно на лабораторной диагностике; представлена большим количеством медицинских офисов по России, а также 13 лабораторными комплексами в городах: Москва, Саратов, Тюмень, Омск, Новосибирск, Новокузнецк, Екатеринбург, Казань, Краснодар, Астрахань, Ростов-на-Дону, Волгоград, Пермь. Наша компания входит в состав ГК Медскан.\n\n'
        'Лабораторная диагностика\n'
        'Сеть лабораторий предлагает полный спектр лабораторных анализов: от рутинных биохимических и общеклинических исследований до секвенирования нового поколения. Работа лабораторной службы в режиме 24/7 позволяет предлагать оптимальные сроки получения результатов исследований. Собственный медицинский обучающий центр группы компаний обеспечивает высокую квалификацию персонала и быстрое внедрение новых диагностических методик.\n\n'
        'Телефон: +7 (495) 640-06-40\n'
        'Сайт: https://kdl.ru/'
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text='🔙 Назад',
            payload='info_organizations'
        )
    )
    
    # Добавление изображения
    attachments = [builder.as_markup()]

    image_url = "static/image/kdl.jpeg"

    photo = InputMedia(path=image_url)
    attachments.insert(0, photo)

    await event.message.answer(
        text=kdl_text,
        attachments=attachments
    )
    

@dp.message_callback(F.callback.payload == 'info_contacts')
async def handle_info_contacts(event: MessageCallback, context: MemoryContext):
    """Обработчик кнопки 'Контакты'"""
    await event.message.delete()
    
    contacts_text = (
        'АО "Медскан"\n\n'
        'Контент:\n'
        'Сайт: https://medscangroup.ru/\n'
        'Телега: https://t.me/Medscan_Group\n\n'
        'Юридический адрес\n'
        '119331, город Москва, пр-кт Вернадского, д. 29, эт/п/к/оф 12/I/4/106\n'
        'ИНН/КПП 7736328675773601001\n'
        'ОГРН 1207700227118'
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text='🔙 Назад',
            payload='btn_info'
        )
    )
    
    await event.message.answer(
        text=contacts_text,
        attachments=[builder.as_markup()]
    )


@dp.message_callback(F.callback.payload == 'back_to_auth_choice')
async def handle_back_to_auth_choice(event: MessageCallback, context: MemoryContext):
    """Возврат к выбору: есть аккаунт или новый пользователь"""
    await context.set_state(None)
    await event.message.delete()
    
    # Получаем данные из контекста для восстановления информации о выбранном времени
    data = await context.get_data()
    selected_time = data.get('selected_time')
    selected_work_date = data.get('selected_work_date')
    
    if selected_time and selected_work_date:
        # Получаем информацию о выбранных данных
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
                text='✍️ Подписать документы онлайн',
                payload='btn_sign_documents'
            )
        )
        builder.row(
            CallbackButton(
                text='🔙 Назад к выбору даты',
                payload='back_to_schedule'
            )
        )
        
        # Форматируем дату для отображения
        try:
            date_obj = datetime.strptime(selected_work_date, "%Y%m%d").date()
            date_display = date_obj.strftime("%d.%m.%Y")
        except (ValueError, TypeError):
            date_display = selected_work_date
        
        await event.message.answer(
            text=f'✅ Вы выбрали время: {selected_time}\n\n'
            f'📅 Дата: {date_display}\n'
            f'📍 Филиал: {branch_name}\n'
            f'🏥 Отделение: {department_name}\n'
            f'👨‍⚕️ Врач: {doctor_name}\n\n'
            f'Для продолжения нужно войти в систему или зарегистрироваться.',
            attachments=[builder.as_markup()]
        )
    else:
        await create_keyboard(event, context)


@dp.message_callback(F.callback.payload == 'back_to_login_username')
async def handle_back_to_login_username(event: MessageCallback, context: MemoryContext):
    """Возврат к вводу логина"""
    await context.set_state(LoginForm.username)
    await event.message.delete()
    
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text='🔙 Назад',
            payload='back_to_auth_choice'
        )
    )
    
    await event.message.answer(
        text='Введите ваш логин:',
        attachments=[builder.as_markup()]
    )


@dp.message_callback(F.callback.payload == 'back_to_main')
async def handle_back_to_main(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    # Удаляем все сообщения, сохраненные для удаления
    await _delete_messages(event, context)
    # Очищаем состояние, если пользователь был в процессе регистрации или авторизации
    await context.set_state(None)
    await create_keyboard(event, context)


@dp.message_callback(F.callback.payload == 'btn_current_appointment')
async def handle_current_appointment_button(event: MessageCallback, context: MemoryContext):
    """Показать список текущих записей на приём (от сегодня на год вперёд). Требуется регистрация и авторизация в МИС."""
    await event.message.delete()
    # Показываем все записи
    await _show_records(event, context)


async def _show_records(event, context: MemoryContext):
    """Показать все записи."""
    # Удаляем все старые сообщения перед показом новых
    await _delete_messages(event, context)
    
    id_max = context.user_id
    dsm = DatabaseSessionManager.create(settings.DB_URL)
    async with dsm.get_session() as session:
        repo = RegisteredUserRepository(session)
        user = await repo.get_by_max_id(id_max)
    if not user:
        await event.message.answer(
            'Для просмотра записей необходима регистрация в системе. Пожалуйста, зарегистрируйтесь.'
        )
        await create_keyboard(event, context)
        return
    
    try:
        # Проверяем, есть ли сохраненные данные записей в контексте
        context_data = await context.get_data()
        cached_data = context_data.get('records_data')
        cached_cookies = context_data.get('records_cookies')
        
        # Если данных нет в кэше, загружаем их
        if not cached_data:
            cookies_dict = {}
            async with InfoClinicaClient(
                base_url=settings.INFOCLINICA_BASE_URL,
                cookies=settings.INFOCLINICA_COOKIES,
                timeout_seconds=settings.INFOCLINICA_TIMEOUT_SECONDS,
            ) as client:
                result = await client.authorize_user(user.cllogin, user.clpassword)
                if result.get('success') and client._client_json.cookies:
                    cookies_dict = dict(client._client_json.cookies)
            if not result.get('success'):
                error_msg = result.get('error', 'Ошибка авторизации в МИС')
                await event.message.answer(
                    f'❌ Не удалось войти в систему записей: {error_msg}\n\n'
                    'Проверьте логин и пароль в личном кабинете.'
                )
                await create_keyboard(event, context)
                return
            if not cookies_dict:
                await event.message.answer(
                    '❌ Ошибка: сессия авторизации не получена. Попробуйте позже.'
                )
                await create_keyboard(event, context)
                return
            
            today = date.today()
            st = today.strftime('%Y%m%d')
            en = (today + timedelta(days=365)).strftime('%Y%m%d')
            async with InfoClinicaClient(
                base_url=settings.INFOCLINICA_BASE_URL,
                cookies=cookies_dict,
                timeout_seconds=settings.INFOCLINICA_TIMEOUT_SECONDS,
            ) as records_client:
                list_result = await records_client.get_records_list(st=st, en=en, start=0, length=100)
            if list_result.status_code != 200 or not list_result.json:
                await event.message.answer(
                    '⚠️ Не удалось загрузить список записей. Попробуйте позже.'
                )
                await create_keyboard(event, context)
                return
            data = list_result.json.get('data') or []
            # Сохраняем данные в контексте
            await context.set_data({
                'records_data': data,
                'records_cookies': cookies_dict
            })
        else:
            data = cached_data
            cookies_dict = cached_cookies
        
        if not data:
            no_records_message = await event.message.answer(
                '📅 У вас нет записей на приём с сегодняшней даты на ближайший год.'
            )
            # Сохраняем ID сообщения для последующего удаления
            if no_records_message:
                current_data = await context.get_data()
                no_records_msg_id = None
                if hasattr(no_records_message, 'message') and no_records_message.message:
                    if hasattr(no_records_message.message, 'body') and no_records_message.message.body:
                        if hasattr(no_records_message.message.body, 'mid'):
                            no_records_msg_id = no_records_message.message.body.mid
                if no_records_msg_id:
                    if 'delete_messages_id' not in current_data:
                        current_data['delete_messages_id'] = []
                    current_data['delete_messages_id'].append(no_records_msg_id)
                    await context.set_data(current_data)
            await create_keyboard(event, context)
            return

        # Сохраняем ID новых сообщений с записями
        delete_messages_id = []

        # Выводим каждую запись отдельным сообщением с кнопкой отмены
        for i, rec in enumerate(data, 1):
            work_date = rec.get('workDate') or ''
            try:
                if len(work_date) == 8:
                    dt = datetime.strptime(work_date, '%Y%m%d').date()
                    work_date = dt.strftime('%d.%m.%Y')
            except (ValueError, TypeError):
                pass
            filial_name = rec.get('filialName') or '—'
            filial_address = rec.get('filialAddress') or '—'
            filial_phone = rec.get('filialPhone') or '—'
            dep_name = rec.get('depName') or '—'
            doc_name = rec.get('docName') or '—'
            start_time = rec.get('startTime') or '—'

            # Ищем идентификатор записи (может быть id, recordId, reservationId и т.д.)
            record_id = rec.get('id') or rec.get('recordId') or rec.get('reservationId') or rec.get('schedid') or None
            # Получаем branch_id (filial) из данных записи
            branch_id = rec.get('filial') or rec.get('branchId') or rec.get('branch_id') or None

            text = (
                f'📅 Дата: {work_date} · Время: {start_time}\n'
                f'📍 Филиал: {filial_name}\n'
                f'🏠 Адрес: {filial_address}\n'
                f'📱 Телефон: {filial_phone}\n'
                f'🏥 Отделение: {dep_name}\n'
                f'👨‍⚕️ Врач: {doc_name}\n'
            )
            
            # Создаем кнопку отмены только если есть идентификатор записи и branch_id
            builder = InlineKeyboardBuilder()
            if record_id and branch_id:
                builder.row(
                    CallbackButton(
                        text='❌ Отменить запись',
                        payload=f'cancel_record_{record_id}_{branch_id}'
                    )
                )
            
            sent_message = await event.message.answer(
                text=text,
                attachments=[builder.as_markup()] if record_id else None
            )
            # Извлекаем ID сообщения сразу после отправки
            # В maxapi SendedMessage имеет атрибут message.body.mid
            if sent_message:
                msg_id = None
                # Пробуем получить mid из message.body.mid
                if hasattr(sent_message, 'message') and sent_message.message:
                    if hasattr(sent_message.message, 'body') and sent_message.message.body:
                        if hasattr(sent_message.message.body, 'mid'):
                            msg_id = sent_message.message.body.mid
                
                if msg_id:
                    delete_messages_id.append(msg_id)
                    logging.info(f"Сохранен ID сообщения (mid): {msg_id}")
                else:
                    logging.warning(f"Не удалось извлечь mid из сообщения. Тип: {type(sent_message)}")
        
        # Сохраняем ID сообщений в контексте
        if delete_messages_id:
            current_data = await context.get_data()
            if 'delete_messages_id' not in current_data:
                current_data['delete_messages_id'] = []
            current_data['delete_messages_id'].extend(delete_messages_id)
            await context.set_data(current_data)
            logging.info(f"Сохранено {len(delete_messages_id)} ID сообщений в контексте")
        
        # Добавляем кнопку "Назад" в главное меню
        builder = InlineKeyboardBuilder()
        builder.row(
            CallbackButton(text='🔙 Назад', payload='back_to_main')
        )

        back_message = await event.message.answer(
            text='📄 Все Ваши записи',
            attachments=[builder.as_markup()]
        )
        # Сохраняем ID сообщения с кнопкой "Назад" для последующего удаления
        if back_message:
            current_data = await context.get_data()
            back_msg_id = None
            # В maxapi SendedMessage имеет атрибут message.body.mid
            if hasattr(back_message, 'message') and back_message.message:
                if hasattr(back_message.message, 'body') and back_message.message.body:
                    if hasattr(back_message.message.body, 'mid'):
                        back_msg_id = back_message.message.body.mid

            if back_msg_id:
                if 'delete_messages_id' not in current_data:
                    current_data['delete_messages_id'] = []
                current_data['delete_messages_id'].append(back_msg_id)
                await context.set_data(current_data)
                logging.info(f"Сохранен ID сообщения с кнопкой 'Назад' (mid): {back_msg_id}")
            else:
                logging.warning(f"Не удалось извлечь mid из сообщения с кнопкой 'Назад'. Тип: {type(back_message)}")
    except Exception as e:
        logging.error(f"Ошибка при загрузке записей: {e}", exc_info=True)
        await event.message.answer(
            f'⚠️ Произошла ошибка при загрузке записей: {str(e)}\n\nПопробуйте позже.'
        )
        await create_keyboard(event, context)


@dp.message_callback(F.callback.payload.startswith('cancel_record_'))
async def handle_cancel_record_button(event: MessageCallback, context: MemoryContext):
    """Обработчик кнопки отмены записи."""
    await event.message.delete()
    # Извлекаем ID записи и branch_id из payload
    payload = event.callback.payload
    # Формат: cancel_record_{record_id}_{branch_id}
    parts = payload.replace('cancel_record_', '').split('_')
    
    if len(parts) < 2:
        await event.message.answer('❌ Ошибка: не удалось определить идентификатор записи или филиала.')
        await create_keyboard(event, context)
        return
    
    record_id = parts[0]
    branch_id = parts[1]
    
    if not record_id or not branch_id:
        await event.message.answer('❌ Ошибка: не удалось определить идентификатор записи или филиала.')
        await create_keyboard(event, context)
        return
    
    id_max = context.user_id
    dsm = DatabaseSessionManager.create(settings.DB_URL)
    async with dsm.get_session() as session:
        repo = RegisteredUserRepository(session)
        user = await repo.get_by_max_id(id_max)
    
    if not user:
        await event.message.answer(
            '❌ Для отмены записи необходима регистрация в системе.'
        )
        await create_keyboard(event, context)
        return
    
    try:
        # Авторизуемся в МИС
        cookies_dict = {}
        async with InfoClinicaClient(
            base_url=settings.INFOCLINICA_BASE_URL,
            cookies=settings.INFOCLINICA_COOKIES,
            timeout_seconds=settings.INFOCLINICA_TIMEOUT_SECONDS,
        ) as client:
            result = await client.authorize_user(user.cllogin, user.clpassword)
            if result.get('success') and client._client_json.cookies:
                cookies_dict = dict(client._client_json.cookies)
        
        if not result.get('success'):
            error_msg = result.get('error', 'Ошибка авторизации в МИС')
            await event.message.answer(
                f'❌ Не удалось войти в систему: {error_msg}\n\n'
                'Проверьте логин и пароль в личном кабинете.'
            )
            await create_keyboard(event, context)
            return
        
        if not cookies_dict:
            await event.message.answer(
                '❌ Ошибка: сессия авторизации не получена. Попробуйте позже.'
            )
            await create_keyboard(event, context)
            return
        
        # Отменяем запись
        async with InfoClinicaClient(
            base_url=settings.INFOCLINICA_BASE_URL,
            cookies=cookies_dict,
            timeout_seconds=settings.INFOCLINICA_TIMEOUT_SECONDS,
        ) as cancel_client:
            cancel_result = await cancel_client.cancel_reservation(record_id, branch_id, raise_for_status=False)

        # Проверяем результат отмены
        if cancel_result and cancel_result.json:
            result_json = cancel_result.json

            if isinstance(result_json, dict) and result_json.get("success") is True:
                # Отмена успешна - очищаем кэш записей, чтобы при следующем запросе загружались свежие данные
                current_data = await context.get_data()
                if 'records_data' in current_data:
                    del current_data['records_data']
                if 'records_cookies' in current_data:
                    del current_data['records_cookies']
                await context.set_data(current_data)
                
                success_message = await event.message.answer('✅ Запись успешно отменена')
                # Сохраняем ID сообщения об успешной отмене для последующего удаления
                # Получаем данные контекста ПОСЛЕ отправки сообщения, как для сообщения "У вас нет записей"
                logging.info(f"[handle_cancel_record_button] Отправлено сообщение об успешной отмене: {success_message}, тип: {type(success_message)}")
                if success_message:
                    current_data = await context.get_data()
                    logging.info(f"[handle_cancel_record_button] Получены данные контекста, ключи: {list(current_data.keys())}")
                    success_msg_id = None
                    if hasattr(success_message, 'message') and success_message.message:
                        if hasattr(success_message.message, 'body') and success_message.message.body:
                            if hasattr(success_message.message.body, 'mid'):
                                success_msg_id = success_message.message.body.mid
                                logging.info(f"[handle_cancel_record_button] Извлечен mid: {success_msg_id}")
                    if success_msg_id:
                        if 'delete_messages_id' not in current_data:
                            current_data['delete_messages_id'] = []
                        current_data['delete_messages_id'].append(success_msg_id)
                        await context.set_data(current_data)
                        logging.info(f"[handle_cancel_record_button] Сохранен ID сообщения об успешной отмене: {success_msg_id}, список: {current_data['delete_messages_id']}")
                        # Проверяем, что данные действительно сохранились
                        verify_data = await context.get_data()
                        logging.info(f"[handle_cancel_record_button] Проверка сохранения: delete_messages_id = {verify_data.get('delete_messages_id', 'НЕ НАЙДЕНО')}")
                    else:
                        logging.warning("[handle_cancel_record_button] Не удалось извлечь ID из сообщения об успешной отмене")
                        if hasattr(success_message, 'message'):
                            logging.warning(f"[handle_cancel_record_button] success_message.message = {success_message.message}")
                        else:
                            logging.warning(f"[handle_cancel_record_button] success_message не имеет атрибута 'message', доступные атрибуты: {dir(success_message)}")
            else:
                # Отмена не удалась
                error_msg = "Не удалось отменить запись"

                if isinstance(result_json, dict):
                    errors = result_json.get("errors", [])

                    if errors and isinstance(errors, list) and len(errors) > 0:
                        error_info = errors[0]
                        if isinstance(error_info, dict) and error_info.get("isError") is True:
                            error_msg = error_info.get("message", error_msg)
                            logging.error(error_msg)

                error_message = await event.message.answer(
                    f'⚠️ {error_msg}\n\n'
                    'Попробуйте обновить список записей.'
                )
                # Сохраняем ID сообщения об ошибке для последующего удаления
                if error_message:
                    current_data = await context.get_data()
                    error_msg_id = None
                    if hasattr(error_message, 'message') and error_message.message:
                        if hasattr(error_message.message, 'body') and error_message.message.body:
                            if hasattr(error_message.message.body, 'mid'):
                                error_msg_id = error_message.message.body.mid
                    if error_msg_id:
                        if 'delete_messages_id' not in current_data:
                            current_data['delete_messages_id'] = []
                        current_data['delete_messages_id'].append(error_msg_id)
                        await context.set_data(current_data)
        else:
            # Результат не получен
            error_message = await event.message.answer(
                '⚠️ Не удалось отменить запись. Возможно, запись уже была отменена или произошла ошибка.\n\n'
                'Попробуйте обновить список записей.'
            )
            # Сохраняем ID сообщения об ошибке для последующего удаления
            if error_message:
                current_data = await context.get_data()
                error_msg_id = None
                if hasattr(error_message, 'message') and error_message.message:
                    if hasattr(error_message.message, 'body') and error_message.message.body:
                        if hasattr(error_message.message.body, 'mid'):
                            error_msg_id = error_message.message.body.mid
                if error_msg_id:
                    if 'delete_messages_id' not in current_data:
                        current_data['delete_messages_id'] = []
                    current_data['delete_messages_id'].append(error_msg_id)
                    await context.set_data(current_data)
        
    except Exception as e:
        logging.error(f"Ошибка при отмене записи: {e}", exc_info=True)
        error_message = await event.message.answer(
            f'❌ Произошла ошибка при отмене записи: {str(e)[:200]}\n\nПопробуйте позже.'
        )
        # Сохраняем ID сообщения об ошибке для последующего удаления
        if error_message:
            current_data = await context.get_data()
            error_msg_id = None
            if hasattr(error_message, 'message') and error_message.message:
                if hasattr(error_message.message, 'body') and error_message.message.body:
                    if hasattr(error_message.message.body, 'mid'):
                        error_msg_id = error_message.message.body.mid
            if error_msg_id:
                if 'delete_messages_id' not in current_data:
                    current_data['delete_messages_id'] = []
                current_data['delete_messages_id'].append(error_msg_id)
                await context.set_data(current_data)
    
    await create_keyboard(event, context)


@dp.message_created(
    lambda e: any(a.type == AttachmentType.CONTACT for a in (e.message.attachments or []))
)
async def handle_contact(event: Message, context: MemoryContext):
    contact = next(a for a in event.message.body.attachments if a.type == AttachmentType.CONTACT)

    vcf = contact.payload.vcf_info
    phone_number = vcf.split("TEL;TYPE=cell:")[1].split("\r\n")[0] if "TEL;TYPE=cell:" in vcf else "не найден"

    client = MaxApiClient()

    res = await client.send_pep_sing(phone_number=phone_number)

    transaction_id = res.get("transactionId")

    poll_max_api_status.delay(f"+{phone_number}", context.user_id, transaction_id)

    await event.message.delete()
    await event.message.answer(
        f"✅ Номер получен: {phone_number}",
    )


@dp.message_callback(F.callback.payload == 'btn_sign_documents')
async def handle_sign_documents_button(event: MessageCallback, context: MemoryContext):
    await event.message.delete()

    text = (
        "📱 Для подписания документа необходимо предоставить номер телефона.\n\n"
        "Нажмите кнопку ниже, чтобы поделиться номером."
    )

    attachments = [
        Attachment(
            type=AttachmentType.INLINE_KEYBOARD,
            payload=ButtonsPayload(
                buttons=[
                    [
                        RequestContactButton(
                            text="📲 Поделиться номером",
                        )
                    ]
                ]
            )
        )
    ]

    builder = InlineKeyboardBuilder()

    builder.row(
        CallbackButton(
            text='🔙 Назад',
            payload='back_to_main'
        )
    )

    await event.message.answer(
        text=text,
        attachments=attachments,
    )


@dp.message_callback(F.callback.payload == 'btn_goskey_signed')
async def handle_goskey_signed(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    logging.info("Пользователь подтвердил подписание документов через Госключ.")
    await event.message.answer(
        text='Спасибо! Мы загрузим подписанные документы и сообщим, когда они будут готовы.'
    )
    await create_keyboard(event, context)


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
    # Удаляем все сообщения, сохраненные для удаления
    await _delete_messages(event, context)
    id_max = context.user_id
    dsm = DatabaseSessionManager.create(settings.DB_URL)
    async with dsm.get_session() as session:
        repo = RegisteredUserRepository(session)
        user = await repo.get_by_max_id(id_max)
    if not user:
        await event.message.answer(
            "Для записи на прием необходима регистрация в системе. Пожалуйста, зарегистрируйтесь."
        )
        await create_keyboard(event, context)
        return
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


def format_schedule_info(
        intervals_data: dict,
        doctor_name: str,
        branch_name: str,
        department_name: str,
        selected_date: date | str,
        doctor_dcode: int | str
):
    """Форматирует информацию о графике работы врача и ближайших доступных временах с кнопками
    Использует данные из get_reservation_intervals в формате:
    {
        "data": [
            {
                "workdates": [
                    {
                        "20260121": [
                            {
                                "schedident": 40075621,
                                "rnum": "202",
                                "dcode": 990102079,
                                "intervals": [
                                    {"time": "08:00-08:30", "isFree": false},
                                    {"time": "09:30-10:00", "isFree": true}
                                ]
                            }
                        ]
                    }
                ]
            }
        ]
    }
    """
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
    
    # Извлекаем данные из ответа get_reservation_intervals
    data_list = intervals_data.get('data', [])
    
    # Собираем все доступные интервалы на выбранную дату
    date_intervals = []
    
    for item in data_list:
        if not isinstance(item, dict):
            continue
        
        workdates = item.get('workdates', [])
        for workdate_item in workdates:
            if not isinstance(workdate_item, dict):
                continue
            
            # Ищем данные для выбранной даты
            if selected_date_str in workdate_item:
                date_data = workdate_item[selected_date_str]
                if isinstance(date_data, list):
                    for schedule_item in date_data:
                        if not isinstance(schedule_item, dict):
                            continue
                        
                        # Проверяем, что это нужный врач
                        if str(schedule_item.get('dcode', '')) != str(doctor_dcode):
                            continue
                        
                        schedident = schedule_item.get('schedident')
                        intervals = schedule_item.get('intervals', [])
                        
                        for interval in intervals:
                            if not isinstance(interval, dict):
                                continue
                            
                            # Проверяем, что интервал свободен
                            is_free = interval.get('isFree', False)
                            time_str = interval.get('time', '')
                            
                            if is_free and time_str:
                                # Сохраняем информацию об интервале
                                interval_info = {
                                    'time': time_str,  # Формат "09:30-10:00"
                                    'schedident': schedident,
                                    'workDate': selected_date_str,
                                    'dcode': doctor_dcode
                                }
                                date_intervals.append(interval_info)
    
    # Сортируем интервалы по времени начала
    def get_start_time(time_str: str) -> str:
        """Извлекает время начала из интервала (09:30-10:00 -> 09:30)"""
        if '-' in time_str:
            return time_str.split('-')[0].strip()
        return time_str
    
    date_intervals.sort(key=lambda x: get_start_time(x['time']))
    
    if date_intervals:
        text_parts.append('')
    else:
        text_parts.append('\n⏰ На выбранную дату свободное время отсутствует.')
        text_parts.append('Попробуйте выбрать другую дату.')
    
    # Создаем кнопки для каждого интервала времени (по 2 кнопки в ряд)
    for i in range(0, len(date_intervals), 2):
        row_intervals = date_intervals[i:i+2]
        buttons = []
        for interval_info in row_intervals:
            time_str = interval_info['time']  # Формат "09:30-10:00"
            schedident = interval_info['schedident']
            work_date = interval_info['workDate']
            
            # Формируем payload: time_schedident_workDate
            # Для времени "09:30-10:00" используем только начало "09:30" в payload
            time_start = get_start_time(time_str)
            payload_data = f"{time_start.replace(':', '')}_{schedident}_{work_date}"
            
            buttons.append(
                CallbackButton(
                    text=time_str,  # Отображаем полный интервал "09:30-10:00"
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
        safe_int(branch_id)
        
        # Получаем интервалы записи на выбранную дату через get_reservation_intervals
        async with InfoClinicaClient(
            base_url=settings.INFOCLINICA_BASE_URL,
            cookies=settings.INFOCLINICA_COOKIES,
            timeout_seconds=settings.INFOCLINICA_TIMEOUT_SECONDS
        ) as client:
            # Используем следующий день как en для получения интервалов
            next_day = (selected_date + timedelta(days=1)).strftime("%Y%m%d")
            selected_date_str = selected_date.strftime("%Y%m%d")
            
            intervals_result = await client.get_reservation_intervals(
                st=selected_date_str,
                en=next_day,
                dcode=doctor_dcode,
                online_mode=0
            )
            
            # Извлекаем данные из ответа
            if intervals_result.status_code == 200 and intervals_result.json:
                intervals_data = intervals_result.json
            else:
                intervals_data = {}
        
        # Форматируем информацию о графике (возвращает текст и клавиатуру)
        schedule_text, time_keyboard = format_schedule_info(
            intervals_data, 
            doctor_name, 
            branch_name, 
            department_name, 
            selected_date,
            doctor_dcode
        )
        
        # Отправляем информацию о графике с кнопками времени
        await event.message.answer(
            text=schedule_text,
            attachments=[time_keyboard.as_markup()]
        )
        
    except Exception as e:
        logging.error(f"Ошибка при получении расписания на дату: {e}")
        await event.message.answer(
            '❌ Ошибка при загрузке расписания на выбранную дату.\n\n'
            'Попробуйте выбрать другую дату или обратитесь в поддержку.'
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
    # Извлекаем данные из payload (формат: time_0930_40075621_20260121)
    # где 0930 - время начала (HHMM), 40075621 - schedident, 20260121 - дата
    payload_parts = event.callback.payload.replace('time_', '').split('_')
    
    if len(payload_parts) >= 3:
        time_str = payload_parts[0]  # Время в формате HHMM (например, 0930)
        schedident = payload_parts[1]  # ID расписания
        work_date = payload_parts[2]  # Дата в формате YYYYMMDD
        
        # Восстанавливаем формат времени (0930 -> 09:30)
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
    
    # Получаем дату из контекста и форматируем её
    selected_work_date = data.get('selected_work_date') or work_date if len(payload_parts) >= 3 else None
    date_display = "Дата не указана"
    if selected_work_date:
        try:
            # Парсим дату из формата YYYYMMDD
            date_obj = datetime.strptime(selected_work_date, "%Y%m%d").date()
            date_display = date_obj.strftime("%d.%m.%Y")
        except (ValueError, TypeError):
            date_display = selected_work_date
    
    await event.message.delete()
    
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text='✅ Подтвердить запись',
            payload='btn_confirm_reservation'
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
        f'📅 Дата: {date_display}\n'
        f'📍 Филиал: {branch_name}\n'
        f'🏥 Отделение: {department_name}\n'
        f'👨‍⚕️ Врач: {doctor_name}\n\n'
        f'Нажмите «Подтвердить запись», чтобы записаться на приём.',
        attachments=[builder.as_markup()]
    )


@dp.message_callback(F.callback.payload == 'btn_confirm_reservation')
async def handle_confirm_reservation(event: MessageCallback, context: MemoryContext):
    """Подтверждение записи: авторизация в МИС по данным из БД и создание записи."""
    await event.message.delete()
    id_max = context.user_id
    dsm = DatabaseSessionManager.create(settings.DB_URL)
    async with dsm.get_session() as session:
        repo = RegisteredUserRepository(session)
        user = await repo.get_by_max_id(id_max)
    if not user:
        await event.message.answer(
            'Пользователь не найден. Для записи на приём необходимо зарегистрироваться в системе.'
        )
        await create_keyboard(event, context)
        return
    data = await context.get_data()
    selected_time = data.get('selected_time')
    selected_work_date = data.get('selected_work_date')
    selected_schedident = data.get('selected_schedident')
    selected_doctor_dcode = data.get('selected_doctor_dcode')
    selected_branch_id = data.get('selected_branch_id')
    selected_department_id = data.get('selected_department_id')
    if not (selected_time and selected_work_date and selected_schedident and selected_doctor_dcode):
        await event.message.answer(
            'Недостаточно данных для записи. Начните выбор времени заново.'
        )
        await create_keyboard(event, context)
        return
    reservation_success = False
    try:
        cookies_dict = {}
        async with InfoClinicaClient(
            base_url=settings.INFOCLINICA_BASE_URL,
            cookies=settings.INFOCLINICA_COOKIES,
            timeout_seconds=settings.INFOCLINICA_TIMEOUT_SECONDS,
        ) as client:
            result = await client.authorize_user(user.cllogin, user.clpassword)
            if result.get('success') and client._client_json.cookies:
                cookies_dict = dict(client._client_json.cookies)
        if not result.get('success'):
            error_msg = result.get('error', 'Ошибка авторизации в МИС')
            await event.message.answer(
                f'❌ Не удалось войти в систему записи: {error_msg}\n\n'
                'Проверьте логин и пароль в личном кабинете или обратитесь в поддержку.'
            )
            await create_keyboard(event, context)
            return
        if not cookies_dict:
            await event.message.answer(
                '❌ Ошибка: сессия авторизации не получена. Попробуйте позже.'
            )
            await create_keyboard(event, context)
            return
        async with InfoClinicaClient(
            base_url=settings.INFOCLINICA_BASE_URL,
            cookies=cookies_dict,
            timeout_seconds=settings.INFOCLINICA_TIMEOUT_SECONDS,
        ) as reservation_client:
            work_date_obj = datetime.strptime(selected_work_date, "%Y%m%d").date()
            next_day = (work_date_obj + timedelta(days=1)).strftime("%Y%m%d")
            intervals_result = await reservation_client.get_reservation_intervals(
                st=selected_work_date,
                en=next_day,
                dcode=selected_doctor_dcode,
                online_mode=0,
            )
            if intervals_result.status_code != 200 or not intervals_result.json:
                await event.message.answer(
                    '⚠️ Не удалось проверить доступность времени. Попробуйте позже.'
                )
                await create_keyboard(event, context)
                return
            intervals = intervals_result.json
            intervals_list = (
                intervals
                if isinstance(intervals, list)
                else (intervals.get('intervals', []) if isinstance(intervals, dict) else [])
            )
            depnum = None
            found_interval = None
            for interval in intervals_list:
                interval_schedident = interval.get('schedident') or interval.get('schedIdent')
                interval_time = interval.get('startInterval') or interval.get('start')
                if (
                    str(interval_schedident) == str(selected_schedident)
                    and interval_time == selected_time
                ):
                    depnum = interval.get('depnum') or interval.get('depNum')
                    found_interval = interval
                    break
            if not depnum and intervals_list:
                for interval in intervals_list:
                    interval_time = interval.get('startInterval') or interval.get('start')
                    if interval_time == selected_time:
                        depnum = interval.get('depnum') or interval.get('depNum')
                        found_interval = interval
                        break
            if not depnum:
                depnum = selected_department_id
            if found_interval and not found_interval.get('isFree', True):
                await event.message.answer(
                    '❌ Выбранное время уже занято. Пожалуйста, выберите другое время.'
                )
                await create_keyboard(event, context)
                return
            end_time = add_30_minutes(selected_time)
            reserve_data = {
                "date": selected_work_date,
                "dcode": int(selected_doctor_dcode),
                "depnum": int(depnum) if depnum else 0,
                "en": end_time,
                "filial": int(selected_branch_id) if selected_branch_id else 0,
                "st": selected_time,
                "timezone": 3,
                "schedident": int(selected_schedident),
                "services": [],
                "onlineType": 0,
                "refid": None,
                "schedid": None,
                "deviceDetect": 2,
            }
            reserve_payload = InfoClinicaReservationReservePayload(**reserve_data)
            reserve_result = await reservation_client.reserve(reserve_payload)
            branches = data.get('branches_list', [])
            departments = data.get('departments_list', [])
            doctors = data.get('doctors_list', [])
            branch_name = "Филиал"
            for branch in branches:
                if str(branch.get("id")) == str(selected_branch_id):
                    branch_name = branch.get("name", "Филиал")
                    break
            department_name = "Отделение"
            for department in departments:
                if str(department.get("id")) == str(selected_department_id):
                    department_name = department.get("name", "Отделение")
                    break
            doctor_name = "Врач"
            for doctor in doctors:
                if str(doctor.get("dcode")) == str(selected_doctor_dcode):
                    doctor_name = doctor.get("name", "Врач")
                    break
            try:
                date_obj = datetime.strptime(selected_work_date, "%Y%m%d").date()
                date_display = date_obj.strftime("%d.%m.%Y")
            except (ValueError, TypeError):
                date_display = selected_work_date
            if reserve_result.status_code == 200 and reserve_result.json:
                reservation_success = True
                reservation_message = (
                    f'✅ Запись на приём успешно создана!\n\n'
                    f'📍 Филиал: {branch_name}\n'
                    f'🏥 Отделение: {department_name}\n'
                    f'👨‍⚕️ Врач: {doctor_name}\n'
                    f'📅 Дата: {date_display}\n'
                    f'🕐 Время: {selected_time}'
                )
            else:
                error_msg = (
                    reserve_result.json.get('error')
                    if reserve_result.json
                    else reserve_result.text
                )
                reservation_message = f'❌ Ошибка при создании записи: {error_msg or "Неизвестная ошибка"}'
        if reservation_success:
            builder = InlineKeyboardBuilder()
            builder.row(
                CallbackButton(
                    text='✍️ Подписать документы онлайн',
                    payload='btn_sign_documents'
                )
            )
            builder.row(
                CallbackButton(
                    text='🔙 В главное меню',
                    payload='back_to_main'
                )
            )
            await event.message.answer(
                text=reservation_message,
                attachments=[builder.as_markup()]
            )
        else:
            await event.message.answer(reservation_message)
    except Exception as e:
        logging.error(f"Ошибка при подтверждении записи: {e}", exc_info=True)
        await event.message.answer(
            f'⚠️ Произошла ошибка при создании записи: {str(e)}\n\n'
            'Попробуйте позже или обратитесь в поддержку.'
        )
    if not reservation_success:
        await create_keyboard(event, context)


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
    
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text='🔙 Назад',
            payload='back_to_auth_choice'
        )
    )
    
    await event.message.answer(
        text='Введите ваш логин:',
        attachments=[builder.as_markup()]
    )


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
    
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(
            text='🔙 Назад',
            payload='back_to_login_username'
        )
    )
    
    await event.message.answer(
        text='Введите ваш пароль:',
        attachments=[builder.as_markup()]
    )


@dp.message_created(F.message.body.text, LoginForm.password)
async def handle_login_password(event: MessageCreated, context: MemoryContext):
    """Обработка ввода пароля и выполнение входа"""
    data = await context.get_data()
    username = data.get('login_username')
    password = event.message.body.text
    
    try:
        # Выполняем вход через InfoClinicaClient
        async with InfoClinicaClient() as client:
            result = await client.authorize_user(username, password)
            
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
                
                message = '✅ Вход выполнен успешно!\n\n'
                if user_info:
                    message += '\n'.join(user_info) + '\n\n'
                message += f'Логин: {username}'
                
                await event.message.answer(message)
                await create_keyboard(event, context)
                
                # Получаем cookies из авторизованного клиента
                authorized_client = result.get('client') or client
                cookies_dict = {}
                if authorized_client and authorized_client._client_json.cookies:
                    cookies_dict = dict(authorized_client._client_json.cookies)
                
                # Сохраняем данные сессии в контекст для дальнейшего использования
                await context.update_data(
                    authenticated=True,
                    user_id=result.get('user_id'),
                    session_data=result,
                    auth_cookies=cookies_dict  # Сохраняем cookies для создания нового клиента при необходимости
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
                    # Проверяем наличие cookies
                    if not cookies_dict:
                        logging.error("Cookies не найдены")
                        await event.message.answer(
                            '❌ Ошибка: cookies авторизации не найдены. Попробуйте войти снова.'
                        )
                        return
                    
                    # Собираем список cookies для логирования
                    cookies_list = list(cookies_dict.keys())
                    logging.info(f"Используем cookies: {cookies_list}")
                    
                    # Создаем новый клиент с сохраненными cookies для выполнения записи
                    try:
                        async with InfoClinicaClient(cookies=cookies_dict) as reservation_client:
                            
                            # Получаем интервалы на выбранную дату
                            # Используем следующий день как en для получения интервалов
                            work_date_obj = datetime.strptime(selected_work_date, "%Y%m%d").date()
                            next_day = (work_date_obj + timedelta(days=1)).strftime("%Y%m%d")
                            
                            intervals_result = await reservation_client.get_reservation_intervals(
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
                                            '❌ Выбранное время уже занято. Пожалуйста, выберите другое время.'
                                        )
                                        return
                                
                                # Вычисляем время окончания (start + 30 минут)
                                end_time = add_30_minutes(selected_time)
                                
                                # Формируем данные для записи
                                reserve_data = {
                                    "date": selected_work_date,
                                    "dcode": int(selected_doctor_dcode),
                                    "depnum": int(depnum) if depnum else 0,
                                    "en": end_time,
                                    "filial": int(selected_branch_id) if selected_branch_id else 0,
                                    "st": selected_time,
                                    "timezone": 3,  # Часовой пояс (3 = Москва)
                                    "schedident": int(selected_schedident),
                                    "services": [],  # Список услуг (обычно пустой)
                                    "onlineType": 0,
                                    "refid": None,  # ID реферала (может быть null)
                                    "schedid": None,  # ID расписания (может быть null)
                                    "deviceDetect": 2  # Тип устройства (2 = desktop/web)
                                }
                                
                                # Логируем данные для отладки
                                logging.info(f"Формируем запись на прием: {reserve_data}")
                                logging.info(f"Клиент доступен: {authorized_client is not None}")
                                if authorized_client:
                                    # Собираем куки из клиента
                                    cookies_list = list(authorized_client._client_json.cookies.keys())
                                    logging.info(f"Куки в клиенте: {cookies_list}")
                                
                                # Выполняем запись через InfoClinicaClient
                                reserve_payload = InfoClinicaReservationReservePayload(**reserve_data)
                                reserve_result = await reservation_client.reserve(reserve_payload)
                                
                                if reserve_result.status_code == 200 and reserve_result.json:
                                    success = True
                                    
                                    # Получаем информацию о филиале, отделении и враче из контекста
                                    data = await context.get_data()
                                    branches = data.get('branches_list', [])
                                    departments = data.get('departments_list', [])
                                    doctors = data.get('doctors_list', [])
                                    
                                    branch_name = "Филиал"
                                    for branch in branches:
                                        if str(branch.get("id")) == str(selected_branch_id):
                                            branch_name = branch.get("name", "Филиал")
                                            break
                                    
                                    department_name = "Отделение"
                                    for department in departments:
                                        if str(department.get("id")) == str(selected_department_id):
                                            department_name = department.get("name", "Отделение")
                                            break
                                    
                                    doctor_name = "Врач"
                                    for doctor in doctors:
                                        if str(doctor.get("dcode")) == str(selected_doctor_dcode):
                                            doctor_name = doctor.get("name", "Врач")
                                            break
                                    
                                    # Форматируем дату для отображения
                                    try:
                                        date_obj = datetime.strptime(selected_work_date, "%Y%m%d").date()
                                        date_display = date_obj.strftime("%d.%m.%Y")
                                    except (ValueError, TypeError):
                                        date_display = selected_work_date
                                    
                                    reservation_message = (
                                        f'✅ Запись на прием успешно создана!\n\n'
                                        f'📍 Филиал: {branch_name}\n'
                                        f'🏥 Отделение: {department_name}\n'
                                        f'👨‍⚕️ Врач: {doctor_name}\n'
                                        f'📅 Дата: {date_display}\n'
                                        f'🕐 Время: {selected_time}'
                                    )
                                else:
                                    success = False
                                    error_msg = reserve_result.json.get('error') if reserve_result.json else reserve_result.text
                                    reservation_message = f'❌ Ошибка при создании записи: {error_msg or "Неизвестная ошибка"}'
                                
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
            '❌ Произошла ошибка при входе.\n\n'
            'Попробуйте позже или обратитесь в поддержку.'
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
                await create_keyboard(event, context)
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
            '❌ Произошла ошибка при регистрации.\n\n'
            'Попробуйте позже или обратитесь в поддержку.'
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
    await create_keyboard(event, context)


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
