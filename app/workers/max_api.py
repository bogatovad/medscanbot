import base64
import logging
import os
import subprocess
import uuid

from pathlib import Path
from typing import Optional

from app.config import settings
from app.providers.max_api import MaxApiClient
from app.tasks import app


FINAL_TRANSACTION_STATUSES = {"cancelled", "error", "finished"}
TARGET_STEP_TYPE = "med_permission"


class OpenSSLSignError(Exception):
    pass


def _ensure_signer_cert_and_key() -> tuple[str, str]:
    """
    Возвращает пути к сертификату и ключу для подписи.
    Если файлы из настроек отсутствуют, генерирует dev-сертификат в MEDIA_ROOT.
    """
    cert_path = settings.OPENSSL_CERT_PATH
    key_path = settings.OPENSSL_KEY_PATH
    if os.path.exists(cert_path) and os.path.exists(key_path):
        return cert_path, key_path
    # Генерируем dev-сертификат в каталоге MEDIA_ROOT (обычно доступен на запись)
    media_root = os.path.abspath(settings.MEDIA_ROOT)
    os.makedirs(media_root, exist_ok=True)
    fallback_cert = os.path.join(media_root, "dev_cert.pem")
    fallback_key = os.path.join(media_root, "dev_key.pem")
    if os.path.exists(fallback_cert) and os.path.exists(fallback_key):
        return fallback_cert, fallback_key
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048",
            "-keyout", fallback_key,
            "-out", fallback_cert,
            "-days", "365",
            "-nodes",
            "-subj", "/CN=medscan-dev",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    return fallback_cert, fallback_key


def create_signature_with_openssl(
    zip_path: str,
    transaction_id: str,
) -> str:
    """
    Создаёт CMS-подпись для ZIP-файла через openssl.

    zip_path       — путь к document.zip
    transaction_id — id транзакции

    Возвращает путь к созданному .sig файлу
    """
    if not os.path.exists(zip_path):
        raise FileNotFoundError(f"ZIP not found: {zip_path}")

    cert_path, key_path = _ensure_signer_cert_and_key()

    base_dir = os.path.join(settings.MEDIA_ROOT, "documents", transaction_id)
    os.makedirs(base_dir, exist_ok=True)

    output_sig_path = os.path.join(base_dir, f"document_{uuid.uuid4().hex}.sig")

    cmd = [
        "openssl",
        "cms",
        "-sign",
        "-binary",
        "-in", zip_path,
        "-out", output_sig_path,
        "-outform", "DER",
        "-signer", cert_path,
        "-inkey", key_path,
        "-nosmimecap",
        "-nocerts",
        "-noattr",
    ]

    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as e:
        raise OpenSSLSignError(
            f"OpenSSL sign failed: {e.stderr.decode(errors='ignore')}"
        )

    return output_sig_path

#
# def unzip_archive(zip_path: str) -> str:
#     zip_path = Path(zip_path)
#     extract_dir = zip_path.with_suffix("")
#
#     with zipfile.ZipFile(zip_path, "r") as z:
#         z.extractall(extract_dir)
#
#     return str(extract_dir)


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


def save_sig(*, content: bytes | str, transaction_id: str) -> str:
    """
    Сохраняет файл подписи (.sig) в media/max_api/{transaction_id}/

    content может быть:
    - bytes
    - base64-строкой
    """

    base_dir = os.path.join(settings.MEDIA_ROOT, "documents", transaction_id)
    os.makedirs(base_dir, exist_ok=True)

    file_path = os.path.join(base_dir, "document.sig")

    # если пришёл base64
    if isinstance(content, str):
        content = base64.b64decode(content)

    with open(file_path, "wb") as f:
        f.write(content)

    return file_path


@app.task(bind=True, max_retries=30, name="app.workers.max_api.poll_max_api_status")
def poll_max_api_status(self, phone_number: str, user_id: int, transaction_id: str):
    client = MaxApiClient()
    try:

        data = client.sync_check_status(transaction_id=transaction_id)

        tx_status = data.get("status")

        if tx_status in {"cancelled", "error"}:
            client.send_message(user_id, "Не удалось подписать документ, попробуйте позднее")
            return None

        steps = data.get("steps", [])
        med_step = next((s for s in steps if s.get("type") == TARGET_STEP_TYPE), None)

        if med_step:
            step_status = med_step.get("status")
            step_data = med_step.get("data") or {}

            id_zip = step_data.get("idZip")
            id_sig = step_data.get("idSig")

            if step_status == "wip_partner" or id_zip or id_sig:
                paths = {}

                if id_zip:
                    zip_resp = client.sync_document_download(
                        transaction_id=transaction_id,
                        field_id=id_zip,
                        phone_number=phone_number,
                    )
                    zip_path = save_zip(
                        content=zip_resp["content"],
                        transaction_id=transaction_id,
                    )
                    paths["zip"] = zip_path

                if id_sig:
                    sig_resp = client.sync_document_download(
                        transaction_id=transaction_id,
                        field_id=id_sig,
                        phone_number=phone_number,
                    )
                    sig_path = save_sig(
                        content=sig_resp["content"],
                        transaction_id=transaction_id,
                    )
                    paths["sig"] = sig_path

                if "zip" in paths:
                    try:
                        output_path = create_signature_with_openssl(
                            zip_path=paths["zip"],
                            transaction_id=transaction_id
                        )
                    except OpenSSLSignError as e:
                        logging.getLogger(__name__).exception(
                            "OpenSSL signing failed: %s", e
                        )
                        client.send_message(
                            user_id,
                            "Не удалось подписать документ, попробуйте позднее.",
                        )
                        return None
                    upload_res = client.upload_document(file_path=output_path, transaction_id=transaction_id)

                    if "fileId" in upload_res:
                        client.send_message(user_id, "Документ успешно подписан")

                return True

        if tx_status == "active":
            raise self.retry(countdown=30)

        return None
    finally:
        client.sync_client_json.close()

