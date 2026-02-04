import logging
import os

import httpx

from typing import Any

from httpx import AsyncClient

from app.config import settings

logger = logging.getLogger(__name__)


class MaxApiClient:

    def __init__(self) -> None:
        self.base_url = settings.MAX_API_URL
        self.token = settings.MAX_API_AUTH_TOKEN
        self.timeout_seconds = float(settings.MAX_API_TIMEOUT_SECONDS)

        self.headers = {
            "Authorization": self.token,
            "Content-Type": "application/json"
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

        self._client_json = AsyncClient(headers=self.headers, **client_kwargs)
        self.sync_client_json = httpx.Client(headers=self.headers, **client_kwargs)

    async def aclose(self) -> None:
        await self._client_json.aclose()

    async def __aenter__(self) -> "MaxApiClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def send_pep_sing(self, phone_number: str, raise_for_status: bool = False):

        form_data = {
            "dealTemplates": [
                {
                    "templateId": "57b8ff88-4f28-4b03-84fb-08764a99af9b",
                    "data": {
                        "type": "med_permission",
                        "templates": [
                            {
                                "templateId": "8e7f9cff-ac5f-4457-99f8-eff9ec3fd706",
                                "title": "Согласие ПДн6"
                            }
                        ],
                        "medicalData": {
                            "serviceInfo": [
                                {
                                    "nameService": "."
                                }
                            ]
                        },
                        "businessData": {
                            "nameExecutor": "ООО Медскан",
                            "regAdrExecutor": "119421, г Москва, ул Обручева, д 21А",
                            "ogrnExecutor": "1207700227118",
                            "innExecutor": "7725819008",
                            "kppExecutor": "772801001"
                        },
                        "variables": [
                            "signerLastName",
                            "signerFirstName",
                            "signerMiddleName",
                            "signerBirthDate",
                            "signerPLV"
                        ]
                    }
                }
            ],
            "dealTypes": [
                "edb57cb5-c080-43e1-8eda-67cb727880ac"
            ],
            "departmentId": "d6e21133-5bbe-433f-96f5-d11986fbbda7",
            "phoneNumber": phone_number  # "+79026851698"

        }

        resp = await self._client_json.post(url="/v1/sign/send", json=form_data)

        if raise_for_status:
            resp.raise_for_status()

        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        return parsed_json

    def sync_check_status(self, transaction_id: str, raise_for_status: bool = False):

        resp = self.sync_client_json.get(url=f"/v1/sign/status/{transaction_id}")

        if raise_for_status:
            resp.raise_for_status()

        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        return parsed_json

    def sync_document_download(
        self,
        transaction_id: str,
        field_id: str,
        phone_number: str,
        raise_for_status: bool = False,
    ) -> dict:
        json_data = {
            "phoneNumber": phone_number,
            "notify": True,
        }

        resp = self.sync_client_json.post(
            url=f"/v1/sign/download/{transaction_id}/{field_id}",
            json=json_data,
        )

        if raise_for_status:
            resp.raise_for_status()

        return {
            "content": resp.content,  # bytes
            "content_type": resp.headers.get("Content-Type"),
            "content_disposition": resp.headers.get("Content-Disposition"),
            "status_code": resp.status_code,
        }

    def upload_document(self, transaction_id: str, file_path: str, raise_for_status: bool = False):

        with open(file_path, "rb") as f:
            files = {
                "file": (
                    os.path.basename(file_path),
                    f,
                    "application/octet-stream",
                )
            }

            data = {"mimeType": "application/octet-stream" }

            resp = httpx.post(
                url=f"{self.base_url}/v1/sign/upload/{transaction_id}",
                files=files,
                data=data,
                headers={"Authorization": self.token},  # без Content-Type!
            )

        if raise_for_status:
            resp.raise_for_status()

        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        return parsed_json

    def complete_sing(self, transaction_id: str, phone_number: str, raise_for_status: bool = False):
        json_data = {
            "phoneNumber": phone_number,
            "templateId": "1e876cb0-4200-452b-aa39-8bebc196f6e9"
        }
        resp = self.sync_client_json.post(f"/v1/sign/complete/{transaction_id}", json=json_data)

        if raise_for_status:
            resp.raise_for_status()

        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        return parsed_json
