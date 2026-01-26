import logging
import httpx

from typing import Any

from httpx import AsyncClient

from app.config import settings

logger = logging.getLogger(__name__)


class ExtApiClient:

    def __init__(self) -> None:
        self.base_url = settings.EXT_API_URL
        self.token = settings.EXT_API_TOKEN
        self.timeout_seconds = float(settings.EXT_API_TIMEOUT_SECONDS)

        self.headers = {
            "Authorization": self.token,
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

    async def aclose(self) -> None:
        await self._client_json.aclose()

    async def __aenter__(self) -> "ExtApiClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def send_pep_sing(self, payload: Any, raise_for_status: bool = False):
        form = payload.to_form() if hasattr(payload, "to_form") else payload

        resp = await self._client_json.post("/send-pep-sing", data=form)

        if raise_for_status:
            resp.raise_for_status()

        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        return parsed_json

    async def check_status(self, transaction_id: str, raise_for_status: bool = False):

        resp = await self._client_json.get(f"/deals/{transaction_id}")

        if raise_for_status:
            resp.raise_for_status()

        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        return parsed_json

    async def get_document_download(
        self,
        transaction_id: str,
        field_id: str,
        raise_for_status: bool = False,
    ):
        resp = await self._client_json.get(f"/deals/{transaction_id}/download/{field_id}")

        if raise_for_status:
            resp.raise_for_status()

        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        return parsed_json

    async def upload_document(self, transaction_id: str, raise_for_status: bool = False):

        resp = await self._client_json.post(f"/deals/{transaction_id}/upload")

        if raise_for_status:
            resp.raise_for_status()

        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        return parsed_json

    async def complete_sing(self, transaction_id: str, raise_for_status: bool = False):
        resp = await self._client_json.post(f"/deals/{transaction_id}/steps")

        if raise_for_status:
            resp.raise_for_status()

        try:
            parsed_json = resp.json()
        except Exception:
            parsed_json = None

        return parsed_json