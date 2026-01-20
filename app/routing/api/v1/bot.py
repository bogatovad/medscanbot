from datetime import date
from typing import Optional

from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse

from maxapi.methods.types.getted_updates import process_update_webhook

from app.bot import bot, dp

router = APIRouter(prefix="/bot", tags=["bot"])


@router.post("/webhook")
async def webhook_handler(request: Request):
    """
    Эндпоинт для обработки вебхук-запросов от MAX мессенджера.
    Реализация на основе низкоуровневого примера из maxapi.
    """
    try:
        # Сериализация полученного запроса
        event_json = await request.json()
        
        # Десериализация полученного запроса в pydantic
        event_object = await process_update_webhook(
            event_json=event_json,
            bot=bot
        )
        
        # Окончательная обработка запроса через dispatcher
        await dp.handle(event_object)
        
        # Ответ вебхука
        return JSONResponse(content={"ok": True}, status_code=200)
    except Exception as e:
        # В случае ошибки возвращаем статус 200, чтобы мессенджер не повторял запрос
        # но логируем ошибку
        return JSONResponse(content={"ok": False, "error": str(e)}, status_code=200)
