"""
Сервис запросов к МИС Infoclinica: филиалы, отделения, врачи, расписание, записи, авторизация.
"""
import logging
from datetime import date, datetime, timedelta
from typing import Any

from app.config import settings
from app.providers.infoclinica_client import InfoClinicaClient
from app.schemas.infoclinica import (
    CreatePatientPayload,
    InfoClinicaReservationReservePayload,
    UpdatePatientCredentialsPayload,
)


def _client_kwargs() -> dict[str, Any]:
    return {
        "base_url": settings.INFOCLINICA_BASE_URL,
        "cookies": settings.INFOCLINICA_COOKIES,
        "timeout_seconds": settings.INFOCLINICA_TIMEOUT_SECONDS,
    }


async def get_branches() -> list[dict]:
    """Получить список всех филиалов."""
    async with InfoClinicaClient(**_client_kwargs()) as client:
        result = await client.filial_list()
        data = result.json or {}
        return data.get("data", [])


async def get_departments(filial_id: int | None = None) -> list[dict]:
    """Получить список отделений с опциональной фильтрацией по филиалу."""
    params = {}
    if filial_id is not None:
        params["f"] = filial_id
    async with InfoClinicaClient(**_client_kwargs()) as client:
        result = await client.reservation_departments(params=params if params else None)
        data = result.json or {}
        return data.get("data", [])


async def get_doctors(
    filial_id: int | None = None,
    department_id: int | None = None,
) -> list[dict]:
    """Получить список врачей с опциональной фильтрацией по филиалу и отделению."""
    params = {}
    if filial_id is not None:
        params["filial"] = filial_id
    if department_id is not None:
        params["departments"] = department_id
    async with InfoClinicaClient(**_client_kwargs()) as client:
        result = await client.sdk_specialists_doctors(params=params if params else None)
        data = result.json or {}
        doctors = data.get("data", [])
        if doctors:
            logging.info(
                "Получены врачи: filial=%s, departments=%s, первый врач = %s",
                filial_id,
                department_id,
                doctors[0] if doctors else None,
            )
        return doctors


async def get_doctor_schedule(
    doctor_dcode: int | str | None = None,
    filial_id: int | str | None = None,
    online_mode: int = 1,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    """Получить график работы врача (reservation/schedule)."""
    if start_date is None:
        start_date = datetime.now().date()
    if end_date is None:
        end_date = start_date + timedelta(days=1)
    st = start_date.strftime("%Y%m%d")
    en = end_date.strftime("%Y%m%d")
    params = {
        "st": st,
        "en": en,
        "doctor": str(doctor_dcode) if doctor_dcode else "",
    }
    if filial_id is not None:
        params["filialId"] = str(filial_id)
    async with InfoClinicaClient(**_client_kwargs()) as client:
        result = await client.reservation_schedule(payload=None, params=params, use_get=True)
        return result.json or {}


async def get_reservation_intervals(
    *,
    st: str,
    en: str,
    dcode: int | str,
    online_mode: int = 0,
) -> Any:
    """Получить доступные интервалы для записи."""
    async with InfoClinicaClient(**_client_kwargs()) as client:
        result = await client.get_reservation_intervals(
            st=st,
            en=en,
            dcode=dcode,
            online_mode=online_mode,
        )
        return result.json


async def get_reservation_intervals_authenticated(
    cookies: dict[str, str],
    *,
    st: str,
    en: str,
    dcode: int | str,
    online_mode: int = 0,
) -> Any:
    """Получить доступные интервалы для записи (с авторизованной сессией)."""
    async with InfoClinicaClient(
        base_url=settings.INFOCLINICA_BASE_URL,
        cookies=cookies,
        timeout_seconds=settings.INFOCLINICA_TIMEOUT_SECONDS,
    ) as client:
        result = await client.get_reservation_intervals(
            st=st,
            en=en,
            dcode=dcode,
            online_mode=online_mode,
        )
        return result.json


async def authorize_user(username: str, password: str) -> dict[str, Any]:
    """
    Авторизовать пользователя в МИС. Возвращает dict с ключами success, error, client, cookies_dict (при success).
    """
    async with InfoClinicaClient(**_client_kwargs()) as client:
        result = await client.authorize_user(username, password)
        if result.get("success") and getattr(client, "_client_json", None) and getattr(client._client_json, "cookies", None):
            result = {**result, "cookies_dict": dict(client._client_json.cookies)}
        return result


async def create_patient(payload: CreatePatientPayload) -> tuple[int, dict | None]:
    """
    Создать пациента в МИС. Возвращает (status_code, json_response).
    """
    async with InfoClinicaClient(**_client_kwargs()) as client:
        result = await client.create_patient(payload)
        return result.status_code, result.json


async def update_patient_credentials(pcode: str, payload: UpdatePatientCredentialsPayload) -> tuple[int, dict | None]:
    """Обновить логин/пароль пациента в МИС. Возвращает (status_code, json_response)."""
    async with InfoClinicaClient(**_client_kwargs()) as client:
        result = await client.update_patient_credentials(pcode, payload)
        return result.status_code, result.json


async def reserve_appointment(
    cookies: dict[str, str],
    payload: InfoClinicaReservationReservePayload,
) -> tuple[int, dict | None]:
    """Создать запись на приём (требуется авторизованная сессия — cookies)."""
    async with InfoClinicaClient(
        base_url=settings.INFOCLINICA_BASE_URL,
        cookies=cookies,
        timeout_seconds=settings.INFOCLINICA_TIMEOUT_SECONDS,
    ) as client:
        result = await client.reserve(payload)
        return result.status_code, result.json


async def get_records_list(
    cookies: dict[str, str],
    st: str,
    en: str,
    start: int = 0,
    length: int = 100,
) -> tuple[int, dict | None]:
    """Список записей пользователя (требуется авторизованная сессия). Возвращает (status_code, json)."""
    async with InfoClinicaClient(
        base_url=settings.INFOCLINICA_BASE_URL,
        cookies=cookies,
        timeout_seconds=settings.INFOCLINICA_TIMEOUT_SECONDS,
    ) as client:
        result = await client.get_records_list(st=st, en=en, start=start, length=length)
        return result.status_code, result.json
