from fastapi import APIRouter

from app.routing.api.v1.info_clinical import router as info_clinical_router

router = APIRouter(prefix="/v1")

router.include_router(info_clinical_router)
