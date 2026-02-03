from __future__ import annotations

from fastapi import APIRouter, Depends

from app.providers.max_api import MaxApiClient
from app.responses.base import BaseResponse
from app.workers.max_api import poll_max_api_status

router = APIRouter(prefix="/ext_api", tags=["EXT API MAX"])


async def get_ext_api_client(
) -> MaxApiClient:
    async with MaxApiClient() as client:
        yield client


@router.get("/send_pep_sing")
async def registration(
    client: MaxApiClient = Depends(get_ext_api_client),
):
    phone = "+79026851698"
    res = await client.send_pep_sing(phone_number=phone)
    transaction_id = res.get("transactionId")
    poll_max_api_status.delay(transaction_id, phone, "test")
    return BaseResponse(ok=True, data=res)



