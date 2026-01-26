from fastapi import APIRouter

from app.routing.api.v1.bot import router as bot_router
from app.routing.api.v1.ext_api import router as ext_api_router

router = APIRouter(prefix="/v1")

router.include_router(bot_router)
router.include_router(ext_api_router)
