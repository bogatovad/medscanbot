import asyncio
import logging
import os

from datetime import datetime, timedelta, date

import httpx

from maxapi import F
from maxapi.context import MemoryContext
from maxapi.enums.attachment import AttachmentType
from maxapi.types import (
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
from app.schemas.infoclinica import CreatePatientPayload, UpdatePatientCredentialsPayload
from app.schemas.infoclinica import (
    InfoClinicaRegistrationPayload,
    InfoClinicaReservationReservePayload,
)
from app.bot.router import router
from app.bot.constants import (
    REGISTRATION_INSTRUCTIONS,
    Form,
    RegistrationForm,
    LoginForm,
    LkRegistrationForm,
    LkChangeCredentialsForm,
    INFO_INTRO,
    TEXT_MISSION,
    TEXT_ORGANIZATIONS_INTRO,
    TEXT_HADASSAH,
    TEXT_YAUZA,
    TEXT_MEDSCAN_LLC,
    TEXT_MEDASSIST_KURSK,
    TEXT_MEDICAL_ON_GROUP,
    TEXT_KDL,
    TEXT_CONTACTS,
    INFO_IMAGE_URLS,
)
from app.bot import messages as msg
from app.bot.services.helpers import (
    download_image_to_temp,
    parse_lk_registration_text,
    parse_login_password,
    validate_phone,
    add_30_minutes,
)
from app.bot.services import user_service as user_svc
from app.bot.services import infoclinica_service as infoclinica_svc
from app.bot.ui.keyboards import (
    build_personal_cabinet_keyboard,
    build_branches_keyboard,
    build_departments_keyboard,
    build_doctors_keyboard,
    build_calendar_keyboard,
    format_schedule_info,
    build_time_confirmation_keyboard,
    build_confirm_reservation_keyboard,
    build_info_menu_keyboard,
    build_info_organizations_keyboard,
    build_info_back_keyboard,
)
from app.bot.handlers.common import create_keyboard

# Регистрация обработчиков из handlers (start, back_to_main и т.д.)
import app.bot.handlers.start  # noqa: F401

logging.basicConfig(level=logging.INFO)
dp.include_routers(router)


@dp.message_callback(F.callback.payload == 'btn_personal_cabinet')
async def handle_personal_cabinet(event: MessageCallback, context: MemoryContext):
    """Кнопка «Личный кабинет» — показываем данные из БД и дату регистрации."""
    await event.message.delete()
    user = await user_svc.get_user_by_max_id(context.user_id)
    if not user:
        await event.message.answer(msg.MSG_USER_NOT_FOUND_START)
        await create_keyboard(event, context)
        return
    reg_date = user.registered_at
    reg_str = reg_date.strftime("%d.%m.%Y %H:%M") if reg_date and hasattr(reg_date, "strftime") else str(reg_date)
    text = msg.PERSONAL_CABINET_TEMPLATE.format(
        lastname=user.lastname,
        firstname=user.firstname,
        midname=user.midname or "—",
        bdate=user.bdate,
        cllogin=user.cllogin,
        clpassword=user.clpassword,
        pcode=user.pcode,
        reg_str=reg_str,
    )
    await event.message.answer(text=text, attachments=[build_personal_cabinet_keyboard().as_markup()])


@dp.message_callback(F.callback.payload == 'btn_change_credentials')
async def handle_change_credentials_button(event: MessageCallback, context: MemoryContext):
    """Кнопка «Поменять логин и пароль» — запрашиваем email и пароль (2 строки), обновляем БД и МИС."""
    await event.message.delete()
    await context.set_state(LkChangeCredentialsForm.data)
    await event.message.answer(msg.MSG_CHANGE_CREDENTIALS_INTRO)


@dp.message_created(F.message.body.text, LkChangeCredentialsForm.data)
async def handle_change_credentials_data(event: MessageCreated, context: MemoryContext):
    """Введены логин и пароль — обновляем cllogin в БД и отправляем оба значения в МИС (PUT credentials)."""
    await context.set_state(None)
    parsed = parse_login_password((event.message.body.text or "").strip())
    if not parsed:
        await event.message.answer(msg.MSG_NEED_TWO_LINES)
        return
    new_login, new_password = parsed
    if not new_login or not new_password:
        await event.message.answer(msg.MSG_LOGIN_PASSWORD_EMPTY)
        return
    id_max = context.user_id
    try:
        user = await user_svc.get_user_by_max_id(id_max)
        if not user:
            await event.message.answer(msg.MSG_USER_NOT_FOUND)
            await create_keyboard(event, context)
            return
        pcode = str(user.pcode)
        await user_svc.update_user_credentials(id_max, cllogin=new_login, clpassword=new_password)
        creds = UpdatePatientCredentialsPayload(cllogin=new_login, clpassword=new_password)
        status, resp_json = await infoclinica_svc.update_patient_credentials(pcode, creds)
        if status in (200, 204):
            await event.message.answer(msg.MSG_CREDENTIALS_UPDATED)
        else:
            err = (resp_json or {}).get("message") if isinstance(resp_json, dict) else "Ошибка МИС"
            await event.message.answer(msg.MSG_CREDENTIALS_UPDATED_BOT_ONLY.format(err))
        await create_keyboard(event, context)
    except Exception as e:
        logging.exception("Ошибка при смене логина и пароля")
        await event.message.answer(msg.MSG_ERROR_GENERIC.format(str(e)[:200]))
        await create_keyboard(event, context)


@dp.message_callback(F.callback.payload == 'btn_delete_account')
async def handle_delete_account(event: MessageCallback, context: MemoryContext):
    """Удаление аккаунта из БД по кнопке «Удалить аккаунт» в личном кабинете."""
    await event.message.delete()
    deleted = await user_svc.delete_user_by_max_id(context.user_id)
    if deleted:
        await event.message.answer(msg.MSG_ACCOUNT_DELETED)
    else:
        await event.message.answer(msg.MSG_ACCOUNT_NOT_FOUND)
    await create_keyboard(event, context)


@dp.message_callback(F.callback.payload == 'btn_lk_registration')
async def handle_lk_registration_button(event: MessageCallback, context: MemoryContext):
    """Кнопка «Регистрация» — запрашиваем данные одним сообщением."""
    await event.message.delete()
    await context.set_state(LkRegistrationForm.data)
    await event.message.answer(REGISTRATION_INSTRUCTIONS)


@dp.message_created(F.message.body.text, LkRegistrationForm.data)
async def handle_lk_registration_data(event: MessageCreated, context: MemoryContext):
    """Обработка введённых данных регистрации ЛК: запрос в МИС (createPatients) и сохранение в БД."""
    text = (event.message.body.text or "").strip()
    payload = parse_lk_registration_text(text)

    if payload is None:
        await event.message.answer(msg.MSG_LK_REGISTRATION_BAD_FORMAT)
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
        status, resp_json = await infoclinica_svc.create_patient(create_payload)
        if status not in (200, 201):
            err = (resp_json or {}).get("message") if isinstance(resp_json, dict) else "Ошибка регистрации в МИС"
            await event.message.answer(msg.MSG_REGISTRATION_FAILED_MIS.format(err))
            return
        pcode = resp_json.get("pcode") if isinstance(resp_json, dict) else resp_json if isinstance(resp_json, str) else None
        if not pcode:
            await event.message.answer(msg.MSG_PCODE_NOT_FOUND)
            return
        await user_svc.save_registered_user(
            id_max=id_max,
            pcode=str(pcode),
            lastname=payload["lastname"],
            firstname=payload["firstname"],
            midname=payload["midname"] or None,
            bdate=payload["bdate"],
            cllogin=payload["cllogin"],
            clpassword=payload["clpassword"],
        )

        await event.message.answer(msg.MSG_REGISTRATION_SUCCESS)
        await create_keyboard(event, context)
    except httpx.ConnectTimeout:
        logging.warning("Таймаут соединения с API регистрации пациентов (МИС)")
        await event.message.answer(msg.MSG_REGISTRATION_TIMEOUT)
    except httpx.ConnectError as e:
        logging.warning("Ошибка соединения с API регистрации пациентов: %s", e)
        await event.message.answer(msg.MSG_REGISTRATION_CONNECT_ERROR)
    except Exception as e:
        logging.exception("Ошибка при регистрации в ЛК")
        await event.message.answer(msg.MSG_REGISTRATION_ERROR.format(str(e)[:200]))


@dp.message_callback(F.callback.payload == 'btn_info')
async def handle_info_button(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    await event.message.answer(
        text=INFO_INTRO,
        attachments=[build_info_menu_keyboard().as_markup()],
    )


@dp.message_callback(F.callback.payload == 'info_mission')
async def handle_info_mission(event: MessageCallback, context: MemoryContext):
    """Обработчик кнопки 'Миссия и ценности'"""
    await event.message.delete()
    builder = build_info_back_keyboard('btn_info')
    attachments = [builder.as_markup()]
    temp_image_path = None
    image_url = INFO_IMAGE_URLS.get("mission", "")
    if image_url:
        temp_image_path = await download_image_to_temp(image_url)
        if temp_image_path:
            attachments.insert(0, InputMedia(path=temp_image_path))
    await event.message.answer(text=TEXT_MISSION, attachments=attachments)
    if temp_image_path and os.path.exists(temp_image_path):
        try:
            os.unlink(temp_image_path)
        except Exception:
            pass


@dp.message_callback(F.callback.payload == 'info_organizations')
async def handle_info_organizations(event: MessageCallback, context: MemoryContext):
    """Обработчик кнопки 'Организации'"""
    await event.message.delete()
    await event.message.answer(
        text=TEXT_ORGANIZATIONS_INTRO,
        attachments=[build_info_organizations_keyboard().as_markup()],
    )


async def _info_subpage_with_image(key: str):
    """Клавиатура «Назад» в организации + опциональное изображение. Возвращает (attachments, temp_path)."""
    builder = build_info_back_keyboard('info_organizations')
    attachments = [builder.as_markup()]
    temp_path = None
    if key in INFO_IMAGE_URLS:
        temp_path = await download_image_to_temp(INFO_IMAGE_URLS[key])
        if temp_path:
            attachments.insert(0, InputMedia(path=temp_path))
    return attachments, temp_path


@dp.message_callback(F.callback.payload == 'info_hadassah')
async def handle_info_hadassah(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    attachments, temp_path = await _info_subpage_with_image("hadassah")
    await event.message.answer(text=TEXT_HADASSAH, attachments=attachments)
    if temp_path and os.path.exists(temp_path):
        try:
            os.unlink(temp_path)
        except Exception:
            pass


@dp.message_callback(F.callback.payload == 'info_yauza')
async def handle_info_yauza(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    attachments, temp_path = await _info_subpage_with_image("yauza")
    await event.message.answer(text=TEXT_YAUZA, attachments=attachments)
    if temp_path and os.path.exists(temp_path):
        try:
            os.unlink(temp_path)
        except Exception:
            pass


@dp.message_callback(F.callback.payload == 'info_medscan_llc')
async def handle_info_medscan_llc(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    attachments, temp_path = await _info_subpage_with_image("medscan_llc")
    await event.message.answer(text=TEXT_MEDSCAN_LLC, attachments=attachments)
    if temp_path and os.path.exists(temp_path):
        try:
            os.unlink(temp_path)
        except Exception:
            pass


@dp.message_callback(F.callback.payload == 'info_medassist_kursk')
async def handle_info_medassist_kursk(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    attachments, temp_path = await _info_subpage_with_image("medassist_kursk")
    await event.message.answer(text=TEXT_MEDASSIST_KURSK, attachments=attachments)
    if temp_path and os.path.exists(temp_path):
        try:
            os.unlink(temp_path)
        except Exception:
            pass


@dp.message_callback(F.callback.payload == 'info_medical_on_group')
async def handle_info_medical_on_group(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    attachments, temp_path = await _info_subpage_with_image("medical_on_group")
    await event.message.answer(text=TEXT_MEDICAL_ON_GROUP, attachments=attachments)
    if temp_path and os.path.exists(temp_path):
        try:
            os.unlink(temp_path)
        except Exception:
            pass


@dp.message_callback(F.callback.payload == 'info_kdl')
async def handle_info_kdl(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    attachments, temp_path = await _info_subpage_with_image("kdl")
    await event.message.answer(text=TEXT_KDL, attachments=attachments)
    if temp_path and os.path.exists(temp_path):
        try:
            os.unlink(temp_path)
        except Exception:
            pass


@dp.message_callback(F.callback.payload == 'info_contacts')
async def handle_info_contacts(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    await event.message.answer(
        text=TEXT_CONTACTS,
        attachments=[build_info_back_keyboard('btn_info').as_markup()],
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
            text=msg.MSG_TIME_SELECTED_LOGIN_REQUIRED.format(
                selected_time=selected_time,
                date_display=date_display,
                branch_name=branch_name,
                department_name=department_name,
                doctor_name=doctor_name,
            ),
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
        text=msg.MSG_ENTER_LOGIN,
        attachments=[builder.as_markup()]
    )


@dp.message_callback(F.callback.payload == 'back_to_main')
async def handle_back_to_main(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    await create_keyboard(event, context)


@dp.message_callback(F.callback.payload == 'btn_current_appointment')
async def handle_current_appointment_button(event: MessageCallback, context: MemoryContext):
    """Показать список текущих записей на приём (от сегодня на год вперёд). Требуется регистрация и авторизация в МИС."""
    await event.message.delete()
    user = await user_svc.get_user_by_max_id(context.user_id)
    if not user:
        await event.message.answer(msg.MSG_NEED_REGISTRATION_FOR_RECORDS)
        await create_keyboard(event, context)
        return
    try:
        result = await infoclinica_svc.authorize_user(user.cllogin, user.clpassword)
        cookies_dict = result.get("cookies_dict") or {}
        if not result.get("success"):
            error_msg = result.get("error", "Ошибка авторизации в МИС")
            await event.message.answer(msg.MSG_LOGIN_FAILED_RECORDS.format(error_msg))
            await create_keyboard(event, context)
            return
        if not cookies_dict:
            await event.message.answer(msg.MSG_SESSION_NOT_RECEIVED)
            await create_keyboard(event, context)
            return
        today = date.today()
        st = today.strftime("%Y%m%d")
        en = (today + timedelta(days=365)).strftime("%Y%m%d")
        status, list_json = await infoclinica_svc.get_records_list(cookies_dict, st=st, en=en, start=0, length=100)
        if status != 200 or not list_json:
            await event.message.answer(msg.MSG_RECORDS_LOAD_FAILED)
            await create_keyboard(event, context)
            return
        data = list_json.get("data") or []
        if not data:
            await event.message.answer(msg.MSG_NO_RECORDS)
            await create_keyboard(event, context)
            return
        lines = [msg.RECORDS_HEADER]
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
            block = msg.RECORD_ITEM_TEMPLATE.format(
                work_date=work_date,
                start_time=start_time,
                filial_name=filial_name,
                filial_address=filial_address,
                filial_phone=filial_phone,
                dep_name=dep_name,
                doc_name=doc_name,
            )
            lines.append(block)
        text = '\n'.join(lines)
        await event.message.answer(text)
    except Exception as e:
        logging.error(f"Ошибка при загрузке записей: {e}", exc_info=True)
        await event.message.answer(msg.MSG_RECORDS_ERROR.format(str(e)))
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
    await event.message.answer(msg.MSG_PHONE_RECEIVED.format(phone_number))


@dp.message_callback(F.callback.payload == 'btn_sign_documents')
async def handle_sign_documents_button(event: MessageCallback, context: MemoryContext):
    await event.message.delete()

    text = msg.MSG_SIGN_DOCUMENTS_INTRO

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
    await event.message.answer(text=msg.MSG_DOCUMENTS_THANKS)
    await create_keyboard(event, context)


async def create_branches_keyboard(event, context: MemoryContext, page: int = 0):
    """Создает клавиатуру со списком филиалов с пагинацией (данные из сервиса, разметка из UI)."""
    data = await context.get_data()
    branches = data.get("branches_list")
    if not branches:
        branches = await infoclinica_svc.get_branches()
        await context.update_data(branches_list=branches, branches_page=0)
    await context.update_data(branches_page=page)
    return build_branches_keyboard(branches, page)


@dp.message_callback(F.callback.payload == 'btn_make_appointment')
async def handle_make_appointment_button(event: MessageCallback, context: MemoryContext):
    await event.message.delete()
    user = await user_svc.get_user_by_max_id(context.user_id)
    if not user:
        await event.message.answer(msg.MSG_NEED_REGISTRATION_FOR_APPOINTMENT)
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


async def create_departments_keyboard(event, context: MemoryContext, page: int = 0):
    """Клавиатура отделений (данные из сервиса, разметка из UI)."""
    data = await context.get_data()
    departments = data.get("departments_list")
    branch_id = data.get("selected_branch_id")
    cached_branch_id = data.get("departments_cached_branch_id")
    if not departments or cached_branch_id != branch_id:
        filial_id = int(branch_id) if branch_id else None
        departments = await infoclinica_svc.get_departments(filial_id=filial_id)
        await context.update_data(
            departments_list=departments,
            departments_page=0,
            departments_cached_branch_id=branch_id,
        )
    await context.update_data(departments_page=page)
    return build_departments_keyboard(departments, page)


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
            text=msg.MSG_SELECTED_BRANCH.format(branch_name, text),
            attachments=[builder.as_markup()]
        )
    else:
        await event.message.delete()
        await event.message.answer(msg.MSG_BRANCH_NOT_FOUND)


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
        text=msg.MSG_SELECTED_BRANCH.format(branch_name, text),
        attachments=[builder.as_markup()]
    )


def _branch_department_names(data: dict) -> tuple[str, str]:
    """Из контекста достаёт названия выбранного филиала и отделения."""
    branch_name, department_name = "Филиал", "Отделение"
    for b in data.get("branches_list") or []:
        if str(b.get("id")) == data.get("selected_branch_id"):
            branch_name = b.get("name", "Филиал")
            break
    for d in data.get("departments_list") or []:
        if str(d.get("id")) == data.get("selected_department_id"):
            department_name = d.get("name", "Отделение")
            break
    return branch_name, department_name


async def create_doctors_keyboard(event, context: MemoryContext, page: int = 0):
    """Клавиатура врачей (данные из сервиса, разметка из UI)."""
    data = await context.get_data()
    doctors = data.get("doctors_list")
    branch_id = data.get("selected_branch_id")
    department_id = data.get("selected_department_id")
    cached_branch_id = data.get("doctors_cached_branch_id")
    cached_department_id = data.get("doctors_cached_department_id")
    if not doctors or cached_branch_id != branch_id or cached_department_id != department_id:
        filial_id = int(branch_id) if branch_id else None
        dept_id = int(department_id) if department_id else None
        doctors = await infoclinica_svc.get_doctors(filial_id=filial_id, department_id=dept_id)
        await context.update_data(
            doctors_list=doctors,
            doctors_page=0,
            doctors_cached_branch_id=branch_id,
            doctors_cached_department_id=department_id,
        )
    await context.update_data(doctors_page=page)
    branch_name, department_name = _branch_department_names(data)
    return build_doctors_keyboard(doctors, page, branch_name, department_name)


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
            text=msg.MSG_SELECTED_BRANCH_DEPT.format(branch_name, department_name, text),
            attachments=[builder.as_markup()]
        )
    else:
        await event.message.delete()
        await event.message.answer(msg.MSG_DEPARTMENT_NOT_FOUND)


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
    
    await event.message.delete()
    await event.message.answer(text=text, attachments=[builder.as_markup()])


def create_calendar_keyboard(doctor_name: str, branch_name: str, department_name: str, days_ahead: int = 14):
    """Создаёт календарь выбора даты (делегирует в UI)."""
    return build_calendar_keyboard(doctor_name, branch_name, department_name, days_ahead)


@dp.message_callback(F.callback.payload.startswith('date_'))
async def handle_date_selection(event: MessageCallback, context: MemoryContext):
    """Обработчик выбора даты из календаря"""
    # Извлекаем дату из payload (формат: date_20250116)
    date_str = event.callback.payload.replace('date_', '')
    
    # Парсим дату из строки YYYYMMDD
    try:
        selected_date = datetime.strptime(date_str, "%Y%m%d").date()
    except ValueError:
        await event.message.answer(msg.MSG_DATE_FORMAT_ERROR)
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
        
        next_day = (selected_date + timedelta(days=1)).strftime("%Y%m%d")
        selected_date_str = selected_date.strftime("%Y%m%d")
        intervals_data = await infoclinica_svc.get_reservation_intervals(
            st=selected_date_str,
            en=next_day,
            dcode=doctor_dcode,
            online_mode=0,
        )
        if not intervals_data:
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
        await event.message.answer(msg.MSG_SCHEDULE_LOAD_ERROR)


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
        await event.message.answer(msg.MSG_DOCTOR_NOT_FOUND)


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
        text=msg.MSG_SELECTED_BRANCH.format(branch_name, text),
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
    builder = build_time_confirmation_keyboard()
    await event.message.answer(
        text=msg.MSG_TIME_SELECTED_CONFIRM.format(
            selected_time=selected_time,
            date_display=date_display,
            branch_name=branch_name,
            department_name=department_name,
            doctor_name=doctor_name,
        ),
        attachments=[builder.as_markup()],
    )


@dp.message_callback(F.callback.payload == 'btn_confirm_reservation')
async def handle_confirm_reservation(event: MessageCallback, context: MemoryContext):
    """Подтверждение записи: авторизация в МИС по данным из БД и создание записи."""
    await event.message.delete()
    user = await user_svc.get_user_by_max_id(context.user_id)
    if not user:
        await event.message.answer(msg.MSG_USER_NOT_FOUND_FOR_APPOINTMENT)
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
        await event.message.answer(msg.MSG_INSUFFICIENT_DATA_FOR_RECORD)
        await create_keyboard(event, context)
        return
    reservation_success = False
    try:
        result = await infoclinica_svc.authorize_user(user.cllogin, user.clpassword)
        cookies_dict = result.get("cookies_dict") or {}
        if not result.get("success"):
            error_msg = result.get('error', 'Ошибка авторизации в МИС')
            await event.message.answer(msg.MSG_LOGIN_FAILED_APPOINTMENT.format(error_msg))
            await create_keyboard(event, context)
            return
        if not cookies_dict:
            await event.message.answer(msg.MSG_SESSION_NOT_RECEIVED)
            await create_keyboard(event, context)
            return
        intervals_data = await infoclinica_svc.get_reservation_intervals_authenticated(
            cookies_dict,
            st=selected_work_date,
            en=(datetime.strptime(selected_work_date, "%Y%m%d").date() + timedelta(days=1)).strftime("%Y%m%d"),
            dcode=selected_doctor_dcode,
            online_mode=0,
        )
        intervals_list = (
            intervals_data
            if isinstance(intervals_data, list)
            else (intervals_data.get("intervals", []) if isinstance(intervals_data, dict) else [])
        )
        depnum = None
        found_interval = None
        for interval in intervals_list:
            interval_schedident = interval.get("schedident") or interval.get("schedIdent")
            interval_time = interval.get("startInterval") or interval.get("start")
            if str(interval_schedident) == str(selected_schedident) and interval_time == selected_time:
                depnum = interval.get("depnum") or interval.get("depNum")
                found_interval = interval
                break
        if not depnum and intervals_list:
            for interval in intervals_list:
                if (interval.get("startInterval") or interval.get("start")) == selected_time:
                    depnum = interval.get("depnum") or interval.get("depNum")
                    found_interval = interval
                    break
        if not depnum:
            depnum = selected_department_id
        if found_interval and not found_interval.get("isFree", True):
            await event.message.answer(msg.MSG_TIME_ALREADY_TAKEN)
            await create_keyboard(event, context)
            return
        end_time = add_30_minutes(selected_time)
        reserve_payload = InfoClinicaReservationReservePayload(
            date=selected_work_date,
            dcode=int(selected_doctor_dcode),
            depnum=int(depnum) if depnum else 0,
            en=end_time,
            filial=int(selected_branch_id) if selected_branch_id else 0,
            st=selected_time,
            timezone=3,
            schedident=int(selected_schedident),
            services=[],
            onlineType=0,
            refid=None,
            schedid=None,
            deviceDetect=2,
        )
        reserve_status, reserve_result = await infoclinica_svc.reserve_appointment(cookies_dict, reserve_payload)
        branches = data.get("branches_list", [])
        departments = data.get("departments_list", [])
        doctors = data.get("doctors_list", [])
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
        if reserve_status == 200 and reserve_result:
            reservation_success = True
            reservation_message = msg.MSG_RESERVATION_SUCCESS.format(
                branch_name=branch_name,
                department_name=department_name,
                doctor_name=doctor_name,
                date_display=date_display,
                selected_time=selected_time,
            )
        else:
            error_msg = (reserve_result or {}).get("error") if isinstance(reserve_result, dict) else "Неизвестная ошибка"
            reservation_message = msg.MSG_RESERVATION_ERROR.format(error_msg)
        if reservation_success:
            await event.message.answer(
                text=reservation_message,
                attachments=[build_confirm_reservation_keyboard().as_markup()],
            )
        else:
            await event.message.answer(reservation_message)
    except Exception as e:
        logging.error(f"Ошибка при подтверждении записи: {e}", exc_info=True)
        await event.message.answer(msg.MSG_CREATE_RECORD_ERROR.format(str(e)))
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
        text=msg.MSG_SELECTED_BRANCH_DEPT.format(branch_name, department_name, text),
        attachments=[builder.as_markup()]
    )


@dp.message_created(F.message.body.text, Form.name)
async def handle_name_input(event: MessageCreated, context: MemoryContext):
    await context.update_data(name=event.message.body.text)

    data = await context.get_data()

    await event.message.answer(msg.MSG_NICE_TO_MEET.format(data['name'].title()))


@dp.message_created(F.message.body.text, Form.age)
async def handle_age_input(event: MessageCreated, context: MemoryContext):
    await context.update_data(age=event.message.body.text)

    await event.message.answer(msg.MSG_AGE_JOKE)


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
        text=msg.MSG_ENTER_LOGIN,
        attachments=[builder.as_markup()]
    )


@dp.message_callback(F.callback.payload == 'new_user')
async def handle_new_user(event: MessageCallback, context: MemoryContext):
    """Обработчик кнопки 'Новый пользователь' - начинаем регистрацию"""
    await context.set_state(RegistrationForm.lastName)
    await event.message.delete()
    await event.message.answer(msg.MSG_REGISTRATION_NEW_USER)


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
        text=msg.MSG_ENTER_PASSWORD,
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
                
                message = msg.MSG_LOGIN_SUCCESS_HEADER
                if user_info:
                    message += '\n'.join(user_info) + '\n\n'
                message += msg.MSG_LOGIN_SUCCESS_LOGIN.format(username)
                
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
                        await event.message.answer(msg.MSG_COOKIES_NOT_FOUND)
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
                                        await event.message.answer(msg.MSG_TIME_ALREADY_TAKEN)
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
                                    
                                    reservation_message = msg.MSG_RESERVATION_SUCCESS.format(
                                        branch_name=branch_name,
                                        department_name=department_name,
                                        doctor_name=doctor_name,
                                        date_display=date_display,
                                        selected_time=selected_time,
                                    )
                                else:
                                    success = False
                                    error_msg = reserve_result.json.get('error') if reserve_result.json else reserve_result.text
                                    reservation_message = msg.MSG_RESERVATION_ERROR.format(error_msg or "Неизвестная ошибка")
                                
                                if success:
                                    await event.message.answer(reservation_message)
                                else:
                                    await event.message.answer(reservation_message)
                            else:
                                await event.message.answer(msg.MSG_CHECK_TIME_FAILED)
                    except Exception as e:
                        logging.error(f"Ошибка при выполнении записи: {e}", exc_info=True)
                        await event.message.answer(msg.MSG_CREATE_RECORD_ERROR.format(str(e)))
            else:
                error_msg = result.get('error', 'Ошибка входа')
                await event.message.answer(msg.MSG_LOGIN_ERROR.format(error_msg))
    except Exception as e:
        logging.error(f"Ошибка при входе: {e}", exc_info=True)
        await event.message.answer(msg.MSG_LOGIN_GENERIC_ERROR)


@dp.message_created(F.message.body.text, RegistrationForm.lastName)
async def handle_registration_lastName(event: MessageCreated, context: MemoryContext):
    """Обработка ввода фамилии"""
    await context.update_data(reg_lastName=event.message.body.text)
    await context.set_state(RegistrationForm.firstName)
    await event.message.answer(msg.MSG_ENTER_FIRST_NAME)


@dp.message_created(F.message.body.text, RegistrationForm.firstName)
async def handle_registration_firstName(event: MessageCreated, context: MemoryContext):
    """Обработка ввода имени"""
    await context.update_data(reg_firstName=event.message.body.text)
    await context.set_state(RegistrationForm.middleName)
    await event.message.answer(msg.MSG_ENTER_MIDDLE_NAME)


@dp.message_created(F.message.body.text, RegistrationForm.middleName)
async def handle_registration_middleName(event: MessageCreated, context: MemoryContext):
    """Обработка ввода отчества"""
    middle_name = event.message.body.text if event.message.body.text != "-" else None
    await context.update_data(reg_middleName=middle_name)
    await context.set_state(RegistrationForm.birthDate)
    await event.message.answer(msg.MSG_ENTER_BIRTH_DATE)


@dp.message_created(F.message.body.text, RegistrationForm.birthDate)
async def handle_registration_birthDate(event: MessageCreated, context: MemoryContext):
    """Обработка ввода даты рождения"""
    await context.update_data(reg_birthDate=event.message.body.text)
    await context.set_state(RegistrationForm.email)
    await event.message.answer(msg.MSG_ENTER_EMAIL)


@dp.message_created(F.message.body.text, RegistrationForm.email)
async def handle_registration_email(event: MessageCreated, context: MemoryContext):
    """Обработка ввода email"""
    await context.update_data(reg_email=event.message.body.text)
    await context.set_state(RegistrationForm.phone)
    await event.message.answer(msg.MSG_ENTER_PHONE)


@dp.message_created(F.message.body.text, RegistrationForm.phone)
async def handle_registration_phone(event: MessageCreated, context: MemoryContext):
    """Обработка ввода телефона с валидацией"""
    phone = event.message.body.text
    
    if not validate_phone(phone):
        await event.message.answer(msg.MSG_PHONE_FORMAT_ERROR)
        return  # Остаемся в том же состоянии
    
    await context.update_data(reg_phone=phone)
    await context.set_state(RegistrationForm.snils)
    await event.message.answer(msg.MSG_ENTER_SNILS)


@dp.message_created(F.message.body.text, RegistrationForm.snils)
async def handle_registration_snils(event: MessageCreated, context: MemoryContext):
    """Обработка ввода СНИЛС"""
    await context.update_data(reg_snils=event.message.body.text)
    await context.set_state(RegistrationForm.gender)
    await event.message.answer(msg.MSG_ENTER_GENDER)


@dp.message_created(F.message.body.text, RegistrationForm.gender)
async def handle_registration_gender(event: MessageCreated, context: MemoryContext):
    """Обработка ввода пола"""
    gender = event.message.body.text
    if gender not in ['1', '2']:
        await event.message.answer(msg.MSG_GENDER_ERROR)
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
        msg.MSG_CONSENT_PERSONAL_DATA,
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
                    msg.MSG_REGISTRATION_DONE_TEMPLATE.format(
                        last_name=data.get("reg_lastName"),
                        first_name=data.get("reg_firstName"),
                        middle_name=data.get("reg_middleName") or "не указано",
                        birth_date=data.get("reg_birthDate"),
                        email=data.get("reg_email"),
                        phone=data.get("reg_phone"),
                        snils=data.get("reg_snils"),
                        gender="Мужской" if data.get("reg_gender") == 1 else "Женский",
                    )
                )
                await create_keyboard(event, context)
            else:
                error_msg = result.json.get('message', 'Ошибка регистрации') if result.json else 'Ошибка регистрации'
                await event.message.delete()
                await event.message.answer(msg.MSG_REGISTRATION_DONE_ERROR.format(error_msg))
    except Exception as e:
        logging.error(f"Ошибка при регистрации: {e}")
        await event.message.delete()
        await event.message.answer(msg.MSG_REGISTRATION_GENERIC_ERROR)


@dp.message_callback(F.callback.payload == 'reject_personal_data')
async def handle_reject_personal_data(event: MessageCallback, context: MemoryContext):
    """Обработка отказа от обработки персональных данных"""
    await event.message.delete()
    await context.set_state(None)
    await event.message.answer(msg.MSG_REGISTRATION_CANCELLED)
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
