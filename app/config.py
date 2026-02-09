from urllib.parse import quote_plus

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Хост БД: в Docker — "postgres", при локальном запуске бота — "127.0.0.1"
    DB_HOST: str = "postgres"
    POSTGRES_USER: str = "user"
    POSTGRES_PASSWORD: str = "password"
    POSTGRES_DB: str = "med_scan"
    POSTGRES_PORT: int = 5432

    @computed_field
    @property
    def DB_URL(self) -> str:
        u = quote_plus(self.POSTGRES_USER)
        p = quote_plus(self.POSTGRES_PASSWORD)
        return f"postgresql+asyncpg://{u}:{p}@{self.DB_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    INFOCLINICA_BASE_URL: str = "https://medscan-t.infoclinica.ru"
    INFOCLINICA_TIMEOUT_SECONDS: float = 30.0
    INFOCLINICA_COOKIES: str = ""
    # API создания/обновления пациентов (МИС): хост, логин/пароль для JWT
    INFOCLINICA_PATIENTS_API_URL: str = "https://10.1.10.186"
    INFOCLINICA_PATIENTS_API_LOGIN: str = "admin"
    INFOCLINICA_PATIENTS_API_PASSWORD: str = "secret"
    # Таймаут для запросов к API пациентов (сек)
    INFOCLINICA_PATIENTS_API_TIMEOUT_SECONDS: float = 60.0

    MAX_BOT_TOKEN: str = ""

    EXT_API_URL: str = "https://ext-api.max.ru"
    EXT_API_TOKEN: str = ""
    EXT_API_TIMEOUT_SECONDS: float = 30.0

    MAX_API_URL: str = "https://platform-api.max.ru"
    MAX_API_AUTH_TOKEN: str = "f9LHodD0cOJd3iZGzkNK8o0c3mbmFFnzup5XEj3qN49yET-uUds5BL-6wvxkp5gd1ofpLoOogJKrDftBXA5q"
    MAX_API_TIMEOUT_SECONDS: float = 30.0

    REDIS_URL: str = "redis://:@redis:6379/0"
    CELERY_BROKER: str = REDIS_URL

    MEDIA_ROOT: str = "media"

    OPENSSL_CERT_PATH: str = "/opt/services/app/src/dev_cert.pem"
    OPENSSL_KEY_PATH: str = "/opt/services/app/src/dev_key.pem"

    # Включение авторизации в боте
    enable_auth: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
