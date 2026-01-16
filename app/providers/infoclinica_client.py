import json as jsonlib
import logging
import time
import httpx

from typing import Any, Mapping

from httpx import AsyncClient

from app.config import settings
from app.schemas.infoclinica import (
    InfoClinicaHttpResult,
    InfoClinicaConfirmRegistrationPayload,
    InfoClinicaChangeTempPasswordPayload,
    InfoClinicaChangePasswordWebPayload,
    InfoClinicaLoginPayload,
    InfoClinicaRefreshTokenLoginPayload,
    InfoClinicaRegistrationPayload,
    InfoClinicaReservationReservePayload,
    InfoClinicaReservationSchedulePayload,
)

logger = logging.getLogger(__name__)


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
            "accept": "application/json, text/javascript, */*; q=0.01",
            "content-type": "application/json; charset=UTF-8",
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
        POST /login with JSON body.

        Mirrors curl:
        - accept: application/json, text/javascript, */*; q=0.01
        - content-type: application/json; charset=UTF-8
        - body: {"accept":false,"code":"","formKey":"pcode","g-recaptcha-response":"",...}
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
            "InfoClinica /login status=%s body=%s",
            resp.status_code,
            (resp.text[:2000] + "…") if len(resp.text) > 2000 else resp.text,
        )
        if parsed_json is not None:
            logger.debug(
                "InfoClinica /login json=%s",
                jsonlib.dumps(parsed_json, ensure_ascii=False)[:2000],
            )

        return InfoClinicaHttpResult(
            status_code=resp.status_code,
            text=resp.text,
            json=parsed_json,
        )

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


