import uuid
from pathlib import Path
from typing import Optional

from app.config import settings
from app.providers.max_api import MaxApiClient
from app.tasks import app


FINAL_TRANSACTION_STATUSES = {"cancelled", "error", "finished"}
TARGET_STEP_TYPE = "med_permission"


def save_zip(
    content: bytes,
    transaction_id: str,
    filename: Optional[str] = None,
    subdir: str = "documents",
) -> str:
    """
    Сохраняет zip-файл в media папку и возвращает путь к файлу
    """
    media_root = Path(settings.MEDIA_ROOT)

    # max_api/<transaction_id>/
    target_dir = media_root / subdir / transaction_id
    target_dir.mkdir(parents=True, exist_ok=True)

    if not filename:
        filename = f"{uuid.uuid4()}.zip"

    file_path = target_dir / filename

    with open(file_path, "wb") as f:
        f.write(content)

    return str(file_path)


@app.task(bind=True, max_retries=30, name="app.workers.max_api.poll_max_api_status")
def poll_max_api_status(self, transaction_id: str, chat_id: int, phone_number: str):
    client = MaxApiClient()
    try:
        data = client.sync_check_status(transaction_id=transaction_id)
        tx_status = data.get("status")
        if tx_status in {"cancelled", "error"}:
            return None

        steps = data.get("steps", [])
        med_step = next((s for s in steps if s.get("type") == TARGET_STEP_TYPE), None)

        if med_step:
            step_status = med_step.get("status")
            step_data = med_step.get("data") or {}

            id_zip = step_data.get("idZip")
            id_sig = step_data.get("idSig")

            if step_status == "wip_partner" or id_zip or id_sig:
                if id_zip:
                    zip_file = client.sync_document_download(
                        transaction_id=transaction_id, field_id=id_zip, phone_number=phone_number
                    )
                    file_name = save_zip(content=zip_file["content"], transaction_id=transaction_id)
                    print(file_name)
                if id_sig:
                    sig_file = client.sync_document_download(
                        transaction_id=transaction_id, field_id=id_zip, phone_number=phone_number
                    )
                    file_name = save_zip(content=sig_file["content"], transaction_id=transaction_id)
                    print(file_name)
                return True

        if tx_status == "active":
            raise self.retry(countdown=30)

        return None
    finally:
        client.sync_client_json.close()

