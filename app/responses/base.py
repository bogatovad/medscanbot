from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class BaseResponse(BaseModel):
    ok: bool = True
    data: Any | None = None
    error: Any | None = None

