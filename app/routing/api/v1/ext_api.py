from __future__ import annotations

from fastapi import APIRouter, Depends

from app.providers.ext_api import ExtApiClient
from app.responses.base import BaseResponse

router = APIRouter(prefix="/ext_api", tags=["EXT API MAX"])


async def get_ext_api_client(
) -> ExtApiClient:
    async with ExtApiClient() as client:
        yield client


@router.get("/transaction-status")
async def registration(
    transaction_id: str,
    client: ExtApiClient = Depends(get_ext_api_client),
):
    res = await client.check_status(transaction_id)
    return BaseResponse(ok=True, data=res)



