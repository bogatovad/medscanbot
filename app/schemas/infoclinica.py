from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _bool_to_str(value: bool | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


class InfoClinicaRegistrationPayload(BaseModel):
    """
    Payload for POST /registration (application/x-www-form-urlencoded).
    Field aliases match the form keys expected by InfoClinica.
    """

    model_config = ConfigDict(populate_by_name=True)

    first_name: str = Field(alias="firstName")
    last_name: str = Field(alias="lastName")
    middle_name: str | None = Field(default=None, alias="middleName")

    refuse_call: bool | str | None = Field(default=None, alias="refuseCall")
    refuse_sms: bool | str | None = Field(default=None, alias="refuseSms")

    # Example from curl: "01.01.2013"
    birth_date: str | None = Field(default=None, alias="birthDate")

    email: str | None = ""
    phone: str | None = ""
    confirmed: str | None = ""
    gender: int | str | None = None
    check_data: str | None = Field(default="", alias="checkData")
    captcha: str | None = ""
    accept: bool | str | None = False
    snils: str | None = ""

    def to_form(self) -> dict[str, str]:
        data: dict[str, Any] = self.model_dump(by_alias=True, exclude_none=False)

        # Normalize boolean-like fields to "true"/"false" strings.
        data["refuseCall"] = _bool_to_str(data.get("refuseCall"))
        data["refuseSms"] = _bool_to_str(data.get("refuseSms"))
        data["accept"] = _bool_to_str(data.get("accept"))

        # Ensure everything is a string for form-urlencoded
        return {k: "" if v is None else str(v) for k, v in data.items()}


class InfoClinicaHttpResult(BaseModel):
    status_code: int
    text: str
    json: Any | None = None


class InfoClinicaConfirmRegistrationPayload(BaseModel):
    """
    Payload for POST /registration/confirm (application/x-www-form-urlencoded).
    Uses dotted form keys: password.password and password.confirm.
    """

    model_config = ConfigDict(populate_by_name=True)

    password: str = Field(alias="password.password")
    confirm: str = Field(alias="password.confirm")

    def to_form(self) -> dict[str, str]:
        data: dict[str, Any] = self.model_dump(by_alias=True, exclude_none=False)
        return {k: "" if v is None else str(v) for k, v in data.items()}


class InfoClinicaLoginPayload(BaseModel):
    """
    Payload for POST /login (application/json).
    """

    model_config = ConfigDict(populate_by_name=True)

    accept: bool = False
    code: str = ""
    form_key: str = Field(default="pcode", alias="formKey")
    g_recaptcha_response: str = Field(default="", alias="g-recaptcha-response")
    password: str
    username: str

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=False)


class InfoClinicaPasswordPair(BaseModel):
    password: str
    confirm: str


class InfoClinicaChangeTempPasswordPayload(BaseModel):
    """
    Payload for POST /change-temp-password (application/json).
    """

    model_config = ConfigDict(populate_by_name=True)

    pwd_token: str = Field(default="", alias="pwdToken")
    password: InfoClinicaPasswordPair

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=False)


class InfoClinicaChangePasswordWebPayload(BaseModel):
    """
    Payload for POST /change-password-web (application/json).
    Example: {"pwdToken":"","password":{"password":"","confirm":""},"code":""}
    """

    model_config = ConfigDict(populate_by_name=True)

    pwd_token: str = Field(default="", alias="pwdToken")
    password: InfoClinicaPasswordPair
    code: str = ""

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=False)


class InfoClinicaRefreshTokenLoginPayload(BaseModel):
    """
    Payload for POST /login refresh flow (application/json).
    Example: {"formKey":"refreshToken","token":"..."}.
    """

    model_config = ConfigDict(populate_by_name=True)

    form_key: str = Field(default="refreshToken", alias="formKey")
    token: str

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=False)


class InfoClinicaReservationReservePayload(BaseModel):
    """
    Payload for POST /api/reservation/reserve (application/json).
    Example:
    {"date":"20251228","dcode":21,"en":"12:00","filial":12,"onlineType":1,
     "schedident":12,"st":"12:00","depnum":12,"refid":"12"}
    """

    date: str
    dcode: int
    en: str
    filial: int
    onlineType: int
    schedident: int
    st: str
    depnum: int
    refid: str

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=False)


class InfoClinicaReservationSchedulePayload(BaseModel):
    """
    Payload for POST /api/reservation/schedule (application/json).
    Example: {"services":[]}
    """

    services: list[Any] = []

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=False)

