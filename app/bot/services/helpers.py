"""
Вспомогательные функции: парсинг, валидация, загрузка файлов.
"""
import logging
import re
import tempfile
from datetime import datetime

import httpx


async def download_image_to_temp(url: str) -> str | None:
    """
    Скачивает изображение по URL во временный файл и возвращает путь к нему.
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            ext = ".jpg"
            if "png" in url.lower() or (response.headers.get("content-type") or "").startswith("image/png"):
                ext = ".png"
            elif "gif" in url.lower() or (response.headers.get("content-type") or "").startswith("image/gif"):
                ext = ".gif"
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_file:
                tmp_file.write(response.content)
                return tmp_file.name
    except Exception as e:
        logging.error("Ошибка при скачивании изображения %s: %s", url, e)
        return None


def parse_lk_registration_text(text: str) -> dict | None:
    """
    Парсит сообщение из 6 строк в словарь для API.
    Возвращает None при ошибке формата или даты.
    """
    lines = [line.strip() for line in (text or "").strip().split("\n") if line.strip()]
    if len(lines) < 6:
        return None
    lastname, firstname, midname, bdate_str, cllogin, clpassword = (
        lines[0], lines[1], lines[2], lines[3], lines[4], lines[5]
    )
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


def parse_login_password(text: str) -> tuple[str, str] | None:
    """Парсит 2 строки: логин, пароль. Возвращает (login, password) или None."""
    lines = [line.strip() for line in (text or "").strip().split("\n") if line.strip()]
    if len(lines) < 2:
        return None
    return lines[0], lines[1]


def validate_phone(phone: str) -> bool:
    """Валидация телефона в формате +7(000)000-00-00."""
    pattern = r"^\+7\(\d{3}\)\d{3}-\d{2}-\d{2}$"
    return bool(re.match(pattern, phone or ""))


def add_30_minutes(time_str: str) -> str:
    """
    Добавляет 30 минут к времени в формате HH:MM.
    Возвращает время в формате HH:MM.
    """
    try:
        hours, minutes = map(int, time_str.split(":"))
        total_minutes = hours * 60 + minutes + 30
        new_hours = (total_minutes // 60) % 24
        new_minutes = total_minutes % 60
        return f"{new_hours:02d}:{new_minutes:02d}"
    except (ValueError, AttributeError) as e:
        logging.error("Ошибка при добавлении 30 минут к времени %s: %s", time_str, e)
        return time_str
