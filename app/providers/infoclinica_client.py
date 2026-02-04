import json as jsonlib
import logging
import time
import httpx

from typing import Any, Mapping

from httpx import AsyncClient

from app.config import settings
from app.schemas.infoclinica import (
    CreatePatientPayload,
    InfoClinicaHttpResult,
    InfoClinicaConfirmRegistrationPayload,
    InfoClinicaChangeTempPasswordPayload,
    InfoClinicaChangePasswordWebPayload,
    InfoClinicaLoginPayload,
    InfoClinicaRefreshTokenLoginPayload,
    InfoClinicaRegistrationPayload,
    InfoClinicaReservationReservePayload,
    InfoClinicaReservationSchedulePayload,
    UpdatePatientCredentialsPayload,
)

logger = logging.getLogger(__name__)


async def _fetch_patients_api_token() -> str:
    """
    POST /token (application/x-www-form-urlencoded) для получения JWT.
    Использует INFOCLINICA_PATIENTS_API_* из настроек.
    """
    base_url = (settings.INFOCLINICA_PATIENTS_API_URL or "").rstrip("/")
    url = f"{base_url}/token"
    timeout = float(settings.INFOCLINICA_PATIENTS_API_TIMEOUT_SECONDS)
    login = settings.INFOCLINICA_PATIENTS_API_LOGIN
    password = settings.INFOCLINICA_PATIENTS_API_PASSWORD
    data = {
        "grant_type": "",
        "username": login,
        "password": password,
        "scope": "",
        "client_id": "",
        "client_secret": "",
    }
    async with AsyncClient(timeout=timeout, verify=False) as client:
        resp = await client.post(url, data=data)
    resp.raise_for_status()
    parsed = resp.json() or {}
    token = parsed.get("access_token") or ""
    if not token:
        raise ValueError("В ответе /token нет access_token")
    return token


class InfoClinicaClient:
    """Client for working with infoclinica.ru ."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        cookies: str | Mapping[str, str] | None = None,
        user_agent: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.base_url = (base_url or settings.INFOCLINICA_BASE_URL).rstrip("/")
        self.timeout_seconds = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else float(settings.INFOCLINICA_TIMEOUT_SECONDS)
        )

        self.user_agent = (
            user_agent
            or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0"
        )

        self.cookies = cookies

        # Build headers ONCE (user request) and keep dedicated clients for different
        # accept/content-type combinations (so we don't pass headers each request).
        base_headers: dict[str, str] = {
            "origin": self.base_url,
            "referer": f"{self.base_url}/sdk",
            "user-agent": self.user_agent,
        }
        if isinstance(self.cookies, str) and self.cookies.strip():
            base_headers["cookie"] = self.cookies

        self._headers_json = {
            **base_headers,
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "wr2-apirequest": "_",
            "x-integration-type": "PORTAL-WR2",
        }

        client_kwargs: dict[str, Any] = {
            "base_url": self.base_url,
            "timeout": self.timeout_seconds,
            "limits": httpx.Limits(
                max_keepalive_connections=20,
                max_connections=100,
                keepalive_expiry=30.0,
            ),
        }
        if isinstance(self.cookies, Mapping):
            client_kwargs["cookies"] = dict(self.cookies)

        self._client_json = AsyncClient(headers=self._headers_json, **client_kwargs)

    async def aclose(self) -> None:
        await self._client_json.aclose()

    async def __aenter__(self) -> "InfoClinicaClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def get_initial_session(self) -> bool:
        """
        Получает начальную сессию (PLAY_SESSION cookie).

        Returns:
            bool: Успешно ли получена сессия
        """
        try:
            resp = await self._client_json.get("/")
            resp.raise_for_status()
            # Проверяем наличие PLAY_SESSION cookie
            cookies = dict(resp.cookies)
            return "PLAY_SESSION" in cookies
        except Exception as e:
            logger.debug(f"Ошибка получения начальной сессии: {e}")
            return False

    async def check_auth_status(
        self,
        *,
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        Проверяет статус авторизации через GET /logged-in.

        Args:
            raise_for_status: Вызывать raise_for_status() при ошибке

        Returns:
            InfoClinicaHttpResult: Результат запроса с данными пользователя
        """
        headers = {"referer": f"{self.base_url}/"}
        resp = await self._client_json.get("/logged-in", headers=headers)
        if raise_for_status:
            resp.raise_for_status()

        parsed_json: Any | None = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        logger.debug(
            "InfoClinica /logged-in status=%s body=%s",
            resp.status_code,
            (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
        )
        if parsed_json is not None:
            logger.debug(
                "InfoClinica /logged-in json=%s",
                jsonlib.dumps(parsed_json, ensure_ascii=False)[:2000],
            )

        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )

    async def registration(
        self,
        payload: InfoClinicaRegistrationPayload,
        *,
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        POST /registration with form-urlencoded body.
        Mirrors the curl example (headers/cookies/form).
        """

        form = payload.to_form()

        resp = await self._client_json.post("/registration", data=form)
        if raise_for_status:
            resp.raise_for_status()

        parsed_json: Any | None = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        # Helpful debug logging (safe: truncates large body)
        logger.debug(
            "InfoClinica /registration status=%s body=%s",
            resp.status_code,
            (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
        )
        if parsed_json is not None:
            logger.debug(
                "InfoClinica /registration json=%s",
                jsonlib.dumps(parsed_json, ensure_ascii=False)[:2000],
            )

        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )

    async def confirm_registration(
        self,
        *,
        r_token: str,
        payload: InfoClinicaConfirmRegistrationPayload,
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        POST /registration/confirm?rToken=... with form-urlencoded body.

        Mirrors curl:
        - accept: application/json, text/javascript, */*; q=0.01
        - body: password.password=...&password.confirm=...
        """

        form = payload.to_form()

        resp = await self._client_json.post(
            "/registration/confirm",
            params={"rToken": r_token},
            data=form,
        )
        if raise_for_status:
            resp.raise_for_status()

        parsed_json: Any | None = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        logger.debug(
            "InfoClinica /registration/confirm status=%s body=%s",
            resp.status_code,
            (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
        )
        if parsed_json is not None:
            logger.debug(
                "InfoClinica /registration/confirm json=%s",
                jsonlib.dumps(parsed_json, ensure_ascii=False)[:2000],
            )

        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )

    async def login(
        self,
        payload: InfoClinicaLoginPayload,
        *,
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        Полный цикл авторизации:
        1. Получает начальную сессию (PLAY_SESSION)
        2. Проверяет текущий статус авторизации
        3. Выполняет авторизацию через POST /login
        4. Проверяет результат авторизации через GET /logged-in

        POST /login with JSON body.

        Mirrors curl:
        - accept: application/json, text/javascript, */*; q=0.01
        - content-type: application/json; charset=UTF-8
        - body: {"accept":false,"code":"","formKey":"pcode","g-recaptcha-response":"",...}
        """
        start_time = time.time()
        username = payload.username

        try:
            # 1. Получаем начальную сессию
            logger.debug(f"[{username}] Получаем начальную сессию...")
            if not await self.get_initial_session():
                logger.warning(f"[{username}] Не удалось получить начальную сессию")
                return InfoClinicaHttpResult(
                    status_code=500,
                    text="Не удалось получить начальную сессию",
                    json={"success": False, "error": "Не удалось получить начальную сессию"},
                )

            # 2. Проверяем, что не авторизованы
            logger.debug(f"[{username}] Проверяем текущий статус...")
            auth_status_result = await self.check_auth_status()
            if auth_status_result.json and auth_status_result.json.get("authenticated"):
                logger.info(f"[{username}] Уже авторизован")
                return InfoClinicaHttpResult(
                    status_code=auth_status_result.status_code,
                    text=auth_status_result.text,
                    json=auth_status_result.json,
                )

            # 3. Авторизуемся
            logger.debug(f"[{username}] Выполняем авторизацию...")
            body = payload.to_json()

            resp = await self._client_json.post("/login", json=body, follow_redirects=True)
            if raise_for_status:
                resp.raise_for_status()

            parsed_json: Any | None = None
            try:
                parsed_json = resp.json()
            except Exception:
                parsed_json = None

            logger.debug(
                "InfoClinica /login status=%s body=%s",
                resp.status_code,
                (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
            )
            if parsed_json is not None:
                logger.debug(
                    "InfoClinica /login json=%s",
                    jsonlib.dumps(parsed_json, ensure_ascii=False)[:2000],
                )

            # 4. Проверяем успешность авторизации по ответу
            # 303 See Other - это нормальный редирект при успешном логине
            # 200 - также может быть успешным ответом
            if resp.status_code not in (200, 303):
                return InfoClinicaHttpResult(
                    status_code=resp.status_code,
                    text=resp.text,
                    json=parsed_json or {"success": False, "error": f"HTTP {resp.status_code}"},
                )

            # Если есть JSON ответ и он указывает на ошибку
            if parsed_json and isinstance(parsed_json, dict) and not parsed_json.get("success", True):
                # Проверяем наличие явного указания на ошибку
                if parsed_json.get("error") or parsed_json.get("message"):
                    return InfoClinicaHttpResult(
                        status_code=resp.status_code,
                        text=resp.text,
                        json=parsed_json,
                    )

            # 5. Проверяем авторизацию через logged-in endpoint
            logger.debug(f"[{username}] Проверяем результат авторизации...")
            auth_status_result = await self.check_auth_status()

            if auth_status_result.status_code == 200:
                user_data = auth_status_result.json
                if user_data and user_data.get("authenticated"):
                    elapsed = time.time() - start_time
                    logger.info(f"[{username}] ✓ Авторизация успешна за {elapsed:.2f} сек")
                    return InfoClinicaHttpResult(
                        status_code=auth_status_result.status_code,
                        text=auth_status_result.text,
                        json=user_data,
                    )
                else:
                    return InfoClinicaHttpResult(
                        status_code=auth_status_result.status_code,
                        text=auth_status_result.text,
                        json=user_data or {"success": False, "error": "Пользователь не авторизован после логина"},
                    )
            else:
                return InfoClinicaHttpResult(
                    status_code=auth_status_result.status_code,
                    text=auth_status_result.text,
                    json=auth_status_result.json or {"success": False, "error": f"Ошибка проверки авторизации: HTTP {auth_status_result.status_code}"},
                )

        except httpx.TimeoutException:
            logger.error(f"[{username}] Таймаут при выполнении запроса")
            return InfoClinicaHttpResult(
                status_code=408,
                text="Таймаут при выполнении запроса",
                json={"success": False, "error": "Таймаут при выполнении запроса"},
            )
        except httpx.ConnectError:
            logger.error(f"[{username}] Ошибка соединения")
            return InfoClinicaHttpResult(
                status_code=503,
                text="Ошибка соединения",
                json={"success": False, "error": "Ошибка соединения"},
            )
        except Exception as e:
            logger.error(f"[{username}] Неизвестная ошибка: {e}", exc_info=True)
            return InfoClinicaHttpResult(
                status_code=500,
                text=f"Неизвестная ошибка: {str(e)}",
                json={"success": False, "error": f"Неизвестная ошибка: {str(e)}"},
            )

    async def authorize_user(
        self,
        username: str,
        password: str,
    ) -> dict[str, Any]:
        """
        Основная функция авторизации пользователя.
        Удобный метод для использования в боте, который возвращает структурированный результат.

        Args:
            username: Логин пользователя
            password: Пароль пользователя

        Returns:
            dict: Результат авторизации с полями:
                - success: bool - успешность авторизации
                - username: str - логин пользователя
                - error: str | None - сообщение об ошибке
                - timestamp: float - время выполнения
                - user_id: int | None - ID пользователя (если успешно)
                - full_name: str | None - полное имя (если успешно)
                - email: str | None - email (если успешно)
                - phone: str | None - телефон (если успешно)
                - authenticated: bool | None - статус авторизации (если успешно)
                - check_token: str | None - токен проверки (если успешно)
                - cookies_obtained: list[str] - список полученных cookies (если успешно)
                - client: InfoClinicaClient - клиент с авторизованной сессией (если успешно)
        """
        logger.info(f"Начинаем авторизацию пользователя: {username}")

        # Создаем payload для авторизации
        payload = InfoClinicaLoginPayload(
            username=username,
            password=password,
        )

        # Выполняем авторизацию
        result = await self.login(payload)

        # Формируем ответ в том же формате, что и старая функция authorize_user
        response_data: dict[str, Any] = {
            "success": False,
            "username": username,
            "error": None,
            "timestamp": time.time(),
        }

        # Проверяем успешность авторизации
        if result.status_code == 200 and result.json:
            user_data = result.json
            if user_data.get("authenticated"):
                response_data.update({
                    "success": True,
                    "user_id": user_data.get("id"),
                    "full_name": user_data.get("fullName"),
                    "email": user_data.get("email"),
                    "phone": user_data.get("phone"),
                    "authenticated": user_data.get("authenticated"),
                    "check_token": user_data.get("checkToken"),
                    "cookies_obtained": list(self._client_json.cookies.keys()) if self._client_json.cookies else [],
                    "client": self,  # Возвращаем сам клиент для дальнейшего использования
                })
            else:
                # Авторизация не удалась
                error_msg = user_data.get("error") or "Пользователь не авторизован после логина"
                response_data["error"] = error_msg
        else:
            # Ошибка авторизации
            error_msg = "Неизвестная ошибка авторизации"
            if result.json and isinstance(result.json, dict):
                error_msg = result.json.get("error") or error_msg
            elif result.text:
                error_msg = result.text[:200]  # Берем первые 200 символов текста ошибки
            response_data["error"] = error_msg

        return response_data

    async def change_temp_password(
        self,
        payload: InfoClinicaChangeTempPasswordPayload,
        *,
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        POST /change-temp-password with JSON body.

        Mirrors curl:
        - accept: application/json, text/javascript, */*; q=0.01
        - content-type: application/json; charset=UTF-8
        - body: {"pwdToken":"","password":{"password":"","confirm":""}}
        """

        body = payload.to_json()

        resp = await self._client_json.post("/change-temp-password", json=body)
        if raise_for_status:
            resp.raise_for_status()

        parsed_json: Any | None = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        logger.debug(
            "InfoClinica /change-temp-password status=%s body=%s",
            resp.status_code,
            (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
        )
        if parsed_json is not None:
            logger.debug(
                "InfoClinica /change-temp-password json=%s",
                jsonlib.dumps(parsed_json, ensure_ascii=False)[:2000],
            )

        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )

    async def login_with_refresh_token(
        self,
        payload: InfoClinicaRefreshTokenLoginPayload,
        *,
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        POST /login with JSON body (refresh token flow).

        Mirrors curl:
        - body: {"formKey":"refreshToken","token":"..."}
        """

        body = payload.to_json()

        resp = await self._client_json.post("/login", json=body)
        if raise_for_status:
            resp.raise_for_status()

        parsed_json: Any | None = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        logger.debug(
            "InfoClinica /login(refreshToken) status=%s body=%s",
            resp.status_code,
            (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
        )
        if parsed_json is not None:
            logger.debug(
                "InfoClinica /login(refreshToken) json=%s",
                jsonlib.dumps(parsed_json, ensure_ascii=False)[:2000],
            )

        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )

    async def forgot_password(
        self,
        *,
        username: str = "",
        captcha: str = "",
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        POST /forgot-password?username=...&captcha=... with empty JSON body.

        Mirrors curl:
        - accept: application/json, text/javascript, */*; q=0.01
        - content-type: application/json; charset=UTF-8
        - body: {}
        """

        resp = await self._client_json.post(
            "/forgot-password",
            params={"username": username, "captcha": captcha},
            json={},
        )
        if raise_for_status:
            resp.raise_for_status()

        parsed_json: Any | None = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        logger.debug(
            "InfoClinica /forgot-password status=%s body=%s",
            resp.status_code,
            (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
        )
        if parsed_json is not None:
            logger.debug(
                "InfoClinica /forgot-password json=%s",
                jsonlib.dumps(parsed_json, ensure_ascii=False)[:2000],
            )

        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )

    async def change_password_web(
        self,
        payload: InfoClinicaChangePasswordWebPayload,
        *,
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        POST /change-password-web with JSON body.

        Mirrors curl:
        - accept: application/json, text/javascript, */*; q=0.01
        - content-type: application/json; charset=UTF-8
        - body: {"pwdToken":"","password":{"password":"","confirm":""},"code":""}
        """

        body = payload.to_json()

        resp = await self._client_json.post("/change-password-web", json=body)
        if raise_for_status:
            resp.raise_for_status()

        parsed_json: Any | None = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        logger.debug(
            "InfoClinica /change-password-web status=%s body=%s",
            resp.status_code,
            (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
        )
        if parsed_json is not None:
            logger.debug(
                "InfoClinica /change-password-web json=%s",
                jsonlib.dumps(parsed_json, ensure_ascii=False)[:2000],
            )

        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )

    async def get_reservation_intervals(
        self,
        *,
        st: str,
        en: str,
        dcode: int | str,
        online_mode: int | str = 1,
        cache_buster: int | None = None,
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        GET /api/reservation/intervals

        Mirrors curl params:
        - st=YYYYMMDD
        - en=YYYYMMDD
        - dcode=...
        - onlineMode=1
        - _=timestamp_ms (optional; auto-generated if not provided)
        """

        if cache_buster is None:
            cache_buster = int(time.time() * 1000)

        params = {
            "st": st,
            "en": en,
            "dcode": dcode,
            "onlineMode": online_mode,
            "_": cache_buster,
        }

        resp = await self._client_json.get("/api/reservation/intervals", params=params)
        if raise_for_status:
            resp.raise_for_status()

        parsed_json: Any | None = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        logger.debug(
            "InfoClinica /api/reservation/intervals status=%s body=%s",
            resp.status_code,
            (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
        )
        if parsed_json is not None:
            logger.debug(
                "InfoClinica /api/reservation/intervals json=%s",
                jsonlib.dumps(parsed_json, ensure_ascii=False)[:2000],
            )

        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )

    async def reserve(
        self,
        payload: InfoClinicaReservationReservePayload,
        *,
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        POST /api/reservation/reserve with JSON body.

        Mirrors curl:
        - accept: application/json, text/javascript, */*; q=0.01
        - content-type: application/json; charset=UTF-8
        """

        body = payload.to_json()

        resp = await self._client_json.post("/api/reservation/reserve", json=body)
        if raise_for_status:
            resp.raise_for_status()

        parsed_json: Any | None = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        logger.debug(
            "InfoClinica /api/reservation/reserve status=%s body=%s",
            resp.status_code,
            (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
        )
        if parsed_json is not None:
            logger.debug(
                "InfoClinica /api/reservation/reserve json=%s",
                jsonlib.dumps(parsed_json, ensure_ascii=False)[:2000],
            )

        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )

    async def get_records_list(
        self,
        *,
        st: str,
        en: str,
        start: int = 0,
        length: int = 25,
        cache_buster: int | None = None,
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        GET /records/list — список записей пользователя (требует авторизации).

        Параметры:
        - st: YYYYMMDD — начало периода
        - en: YYYYMMDD — конец периода
        - start: смещение (по умолчанию 0)
        - length: количество записей (по умолчанию 25)
        """
        if cache_buster is None:
            cache_buster = int(time.time() * 1000)
        params = {
            "st": st,
            "en": en,
            "start": start,
            "length": length,
            "_": cache_buster,
        }
        resp = await self._client_json.get("/records/list", params=params)
        if raise_for_status:
            resp.raise_for_status()
        parsed_json: Any | None = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None
        logger.debug(
            "InfoClinica /records/list status=%s",
            resp.status_code,
        )
        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )

    async def record_confirm(
        self,
        *,
        schedid: str,
        filialid: str,
        cache_buster: int | None = None,
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        GET /record/confirm?schedid=...&filialid=...&_=timestamp_ms

        Mirrors curl params:
        - schedid=...
        - filialid=...
        - _=timestamp_ms (optional; auto-generated if not provided)
        """

        if cache_buster is None:
            cache_buster = int(time.time() * 1000)

        params = {
            "schedid": schedid,
            "filialid": filialid,
            "_": cache_buster,
        }

        resp = await self._client_json.get("/record/confirm", params=params)
        if raise_for_status:
            resp.raise_for_status()

        parsed_json: Any | None = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        logger.debug(
            "InfoClinica /record/confirm status=%s body=%s",
            resp.status_code,
            (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
        )
        if parsed_json is not None:
            logger.debug(
                "InfoClinica /record/confirm json=%s",
                jsonlib.dumps(parsed_json, ensure_ascii=False)[:2000],
            )

        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )

    async def geoip_addr_regions(
        self,
        *,
        cache_buster: int | None = None,
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        GET /geoip/addr-regions?_=timestamp_ms
        """

        if cache_buster is None:
            cache_buster = int(time.time() * 1000)

        resp = await self._client_json.get(
            "/geoip/addr-regions",
            params={"_": cache_buster},
        )
        if raise_for_status:
            resp.raise_for_status()

        parsed_json: Any | None = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        logger.debug(
            "InfoClinica /geoip/addr-regions status=%s body=%s",
            resp.status_code,
            (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
        )
        if parsed_json is not None:
            logger.debug(
                "InfoClinica /geoip/addr-regions json=%s",
                jsonlib.dumps(parsed_json, ensure_ascii=False)[:2000],
            )

        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )

    async def geoip_addr_locality(
        self,
        *,
        cache_buster: int | None = None,
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        GET /geoip/addr-locality?_=timestamp_ms
        """

        if cache_buster is None:
            cache_buster = int(time.time() * 1000)

        resp = await self._client_json.get(
            "/geoip/addr-locality",
            params={"_": cache_buster},
        )
        if raise_for_status:
            resp.raise_for_status()

        parsed_json: Any | None = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        logger.debug(
            "InfoClinica /geoip/addr-locality status=%s body=%s",
            resp.status_code,
            (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
        )
        if parsed_json is not None:
            logger.debug(
                "InfoClinica /geoip/addr-locality json=%s",
                jsonlib.dumps(parsed_json, ensure_ascii=False)[:2000],
            )

        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )

    async def filial_list(
        self,
        *,
        cache_buster: int | None = None,
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        GET /filial?_=timestamp_ms
        """

        if cache_buster is None:
            cache_buster = int(time.time() * 1000)

        resp = await self._client_json.get("/filial", params={"_": cache_buster})
        if raise_for_status:
            resp.raise_for_status()

        parsed_json: Any | None = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        logger.debug(
            "InfoClinica /filial status=%s body=%s",
            resp.status_code,
            (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
        )
        if parsed_json is not None:
            logger.debug(
                "InfoClinica /filial json=%s",
                jsonlib.dumps(parsed_json, ensure_ascii=False)[:2000],
            )

        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )

    async def reservation_departments(
        self,
        *,
        params: dict[str, Any] | None = None,
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        POST /api/reservation/departments with empty JSON body ({}).
        Curl uses --data-raw '{}' and content-type application/json; charset=UTF-8.
        """

        resp = await self._client_json.post(
            "/api/reservation/departments",
            params=params or {},
            json={},
        )
        if raise_for_status:
            resp.raise_for_status()

        parsed_json: Any | None = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        logger.debug(
            "InfoClinica /api/reservation/departments status=%s body=%s",
            resp.status_code,
            (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
        )
        if parsed_json is not None:
            logger.debug(
                "InfoClinica /api/reservation/departments json=%s",
                jsonlib.dumps(parsed_json, ensure_ascii=False)[:2000],
            )

        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )

    async def doctor_mark(
        self,
        *,
        params: dict[str, Any] | None = None,
        cache_buster: int | None = None,
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        GET /doctor/mark?_=timestamp_ms
        """

        if cache_buster is None:
            cache_buster = int(time.time() * 1000)

        merged_params = {**(params or {}), "_": cache_buster}

        resp = await self._client_json.get("/doctor/mark", params=merged_params)
        if raise_for_status:
            resp.raise_for_status()

        parsed_json: Any | None = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        logger.debug(
            "InfoClinica /doctor/mark status=%s body=%s",
            resp.status_code,
            (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
        )
        if parsed_json is not None:
            logger.debug(
                "InfoClinica /doctor/mark json=%s",
                jsonlib.dumps(parsed_json, ensure_ascii=False)[:2000],
            )

        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )

    async def sdk_specialists_doctors(
        self,
        *,
        params: dict[str, Any] | None = None,
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        POST /sdk/specialists/doctors with empty JSON body ({}).
        """

        resp = await self._client_json.post(
            "/sdk/specialists/doctors",
            params=params or {},
            json={},
        )
        if raise_for_status:
            resp.raise_for_status()

        parsed_json: Any | None = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        logger.debug(
            "InfoClinica /sdk/specialists/doctors status=%s body=%s",
            resp.status_code,
            (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
        )
        if parsed_json is not None:
            logger.debug(
                "InfoClinica /sdk/specialists/doctors json=%s",
                jsonlib.dumps(parsed_json, ensure_ascii=False)[:2000],
            )

        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )

    async def create_patient(
        self,
        payload: CreatePatientPayload,
        *,
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        POST /createPatients/ — регистрация пациента в МИС.
        Сначала получает JWT через POST /token, затем запрос с заголовком Authorization.
        В ответе ожидается pcode (идентификатор пациента в ИК).
        """
        token = await _fetch_patients_api_token()
        base_url = settings.INFOCLINICA_PATIENTS_API_URL.rstrip("/")
        url = f"{base_url}/createPatients/"
        body = payload.to_json()
        timeout_patients = float(settings.INFOCLINICA_PATIENTS_API_TIMEOUT_SECONDS)
        headers = {"Authorization": f"Bearer {token}"}
        async with AsyncClient(
            timeout=timeout_patients,
            verify=False,
        ) as client:
            resp = await client.post(url, json=body, headers=headers)
        if raise_for_status:
            resp.raise_for_status()
        parsed_json: Any | None = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None
        logger.debug(
            "InfoClinica POST /createPatients/ status=%s body=%s",
            resp.status_code,
            (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
        )
        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )

    async def update_patient_credentials(
        self,
        pcode: str,
        payload: UpdatePatientCredentialsPayload,
        *,
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        PUT /updatePatients/{pcode}/credentials — обновление логина и пароля пациента в МИС.
        """
        token = await _fetch_patients_api_token()
        base_url = (settings.INFOCLINICA_PATIENTS_API_URL or settings.INFOCLINICA_BASE_URL).rstrip("/")
        url = f"{base_url}/updatePatients/{pcode}/credentials"
        body = payload.to_json()
        timeout_patients = float(settings.INFOCLINICA_PATIENTS_API_TIMEOUT_SECONDS)
        headers = {"Authorization": f"Bearer {token}"}
        async with AsyncClient(
            timeout=timeout_patients,
            verify=False,
        ) as client:
            resp = await client.put(url, json=body, headers=headers)
        if raise_for_status:
            resp.raise_for_status()
        parsed_json: Any | None = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None
        logger.debug(
            "InfoClinica PUT /updatePatients/.../credentials status=%s body=%s",
            resp.status_code,
            (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
        )
        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )

    async def reservation_schedule(
        self,
        payload: InfoClinicaReservationSchedulePayload | None = None,
        *,
        params: dict[str, Any] | None = None,
        use_get: bool = False,
        raise_for_status: bool = False,
    ) -> InfoClinicaHttpResult:
        """
        POST /api/reservation/schedule with JSON body (default)
        or GET /api/reservation/schedule with query parameters (if use_get=True)
        """

        if use_get:
            # GET запрос с query параметрами
            resp = await self._client_json.get(
                "/api/reservation/schedule",
                params=params or {},
            )
        else:
            # POST запрос с JSON body
            body = payload.to_json() if payload else {}

            resp = await self._client_json.post(
                "/api/reservation/schedule",
                params=params or {},
                json=body,
            )
        if raise_for_status:
            resp.raise_for_status()

        parsed_json: Any | None = None
        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        logger.debug(
            "InfoClinica /api/reservation/schedule status=%s body=%s",
            resp.status_code,
            (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
        )
        if parsed_json is not None:
            logger.debug(
                "InfoClinica /api/reservation/schedule json=%s",
                jsonlib.dumps(parsed_json, ensure_ascii=False)[:2000],
            )

        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )


    