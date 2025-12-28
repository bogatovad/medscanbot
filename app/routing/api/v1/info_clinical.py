from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.config import settings
from app.providers.infoclinica_client import InfoClinicaClient
from app.responses.base import BaseResponse
from app.schemas.infoclinica import (
    InfoClinicaChangePasswordWebPayload,
    InfoClinicaChangeTempPasswordPayload,
    InfoClinicaConfirmRegistrationPayload,
    InfoClinicaLoginPayload,
    InfoClinicaRefreshTokenLoginPayload,
    InfoClinicaRegistrationPayload,
    InfoClinicaReservationReservePayload,
    InfoClinicaReservationSchedulePayload,
)

router = APIRouter(prefix="/infoclinica", tags=["infoclinica"])


async def get_infoclinica_client(
    cookies: str = Query(default="", description="Raw Cookie header; if empty uses Settings.INFOCLINICA_COOKIES"),
) -> InfoClinicaClient:
    async with InfoClinicaClient(cookies=cookies or settings.INFOCLINICA_COOKIES) as client:
        yield client

@router.post("/registration")
async def registration(
    payload: InfoClinicaRegistrationPayload,
    client: InfoClinicaClient = Depends(get_infoclinica_client),
):
    res = await client.registration(payload)
    return BaseResponse(ok=True, data=res.model_dump())


@router.post("/registration/confirm")
async def registration_confirm(
    payload: InfoClinicaConfirmRegistrationPayload,
    r_token: str = Query(default="", alias="rToken"),
    client: InfoClinicaClient = Depends(get_infoclinica_client),
):
    res = await client.confirm_registration(r_token=r_token, payload=payload)
    return BaseResponse(ok=True, data=res.model_dump())


@router.post("/login")
async def login(
    payload: InfoClinicaLoginPayload,
    client: InfoClinicaClient = Depends(get_infoclinica_client),
):
    res = await client.login(payload)
    return BaseResponse(ok=True, data=res.model_dump())


@router.post("/login/refresh")
async def login_refresh(
    payload: InfoClinicaRefreshTokenLoginPayload,
    client: InfoClinicaClient = Depends(get_infoclinica_client),
):
    res = await client.login_with_refresh_token(payload)
    return BaseResponse(ok=True, data=res.model_dump())


@router.post("/change-temp-password")
async def change_temp_password(
    payload: InfoClinicaChangeTempPasswordPayload,
    client: InfoClinicaClient = Depends(get_infoclinica_client),
):
    res = await client.change_temp_password(payload)
    return BaseResponse(ok=True, data=res.model_dump())


@router.post("/change-password-web")
async def change_password_web(
    payload: InfoClinicaChangePasswordWebPayload,
    client: InfoClinicaClient = Depends(get_infoclinica_client),
):
    res = await client.change_password_web(payload)
    return BaseResponse(ok=True, data=res.model_dump())


@router.post("/forgot-password")
async def forgot_password(
    username: str = Query(default=""),
    captcha: str = Query(default=""),
    client: InfoClinicaClient = Depends(get_infoclinica_client),
):
    res = await client.forgot_password(username=username, captcha=captcha)
    return BaseResponse(ok=True, data=res.model_dump())


@router.get("/api/reservation/intervals")
async def reservation_intervals(
    st: str = Query(..., description="YYYYMMDD"),
    en: str = Query(..., description="YYYYMMDD"),
    dcode: str = Query(...),
    onlineMode: int = Query(1),
    cache_buster: int | None = Query(default=None, alias="_"),
    client: InfoClinicaClient = Depends(get_infoclinica_client),
):
    res = await client.get_reservation_intervals(
        st=st,
        en=en,
        dcode=dcode,
        online_mode=onlineMode,
        cache_buster=cache_buster,
    )
    return BaseResponse(ok=True, data=res.model_dump())


@router.post("/api/reservation/reserve")
async def reservation_reserve(
    payload: InfoClinicaReservationReservePayload,
    client: InfoClinicaClient = Depends(get_infoclinica_client),
):
    res = await client.reserve(payload)
    return BaseResponse(ok=True, data=res.model_dump())


@router.post("/api/reservation/schedule")
async def reservation_schedule(
    payload: InfoClinicaReservationSchedulePayload,
    client: InfoClinicaClient = Depends(get_infoclinica_client),
):
    res = await client.reservation_schedule(payload)
    return BaseResponse(ok=True, data=res.model_dump())


@router.post("/api/reservation/departments")
async def reservation_departments(
    client: InfoClinicaClient = Depends(get_infoclinica_client),
):
    res = await client.reservation_departments()
    return BaseResponse(ok=True, data=res.model_dump())


@router.get("/record/confirm")
async def record_confirm(
    schedid: str = Query(""),
    filialid: str = Query(""),
    cache_buster: int | None = Query(default=None, alias="_"),
    client: InfoClinicaClient = Depends(get_infoclinica_client),
):
    res = await client.record_confirm(
        schedid=schedid,
        filialid=filialid,
        cache_buster=cache_buster,
    )
    return BaseResponse(ok=True, data=res.model_dump())


@router.get("/geoip/addr-regions")
async def geoip_addr_regions(
    cache_buster: int | None = Query(default=None, alias="_"),
    client: InfoClinicaClient = Depends(get_infoclinica_client),
):
    res = await client.geoip_addr_regions(cache_buster=cache_buster)
    return BaseResponse(ok=True, data=res.model_dump())


@router.get("/geoip/addr-locality")
async def geoip_addr_locality(
    cache_buster: int | None = Query(default=None, alias="_"),
    client: InfoClinicaClient = Depends(get_infoclinica_client),
):
    res = await client.geoip_addr_locality(cache_buster=cache_buster)
    return BaseResponse(ok=True, data=res.model_dump())


@router.get("/filial")
async def filial_list(
    cache_buster: int | None = Query(default=None, alias="_"),
    client: InfoClinicaClient = Depends(get_infoclinica_client),
):
    res = await client.filial_list(cache_buster=cache_buster)
    return BaseResponse(ok=True, data=res.model_dump())


@router.get("/doctor/mark")
async def doctor_mark(
    cache_buster: int | None = Query(default=None, alias="_"),
    client: InfoClinicaClient = Depends(get_infoclinica_client),
):
    res = await client.doctor_mark(cache_buster=cache_buster)
    return BaseResponse(ok=True, data=res.model_dump())


@router.post("/sdk/specialists/doctors")
async def sdk_specialists_doctors(
    client: InfoClinicaClient = Depends(get_infoclinica_client),
):
    res = await client.sdk_specialists_doctors()
    return BaseResponse(ok=True, data=res.model_dump())


