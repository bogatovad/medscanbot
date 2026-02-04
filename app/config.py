from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DB_URL: str = "postgresql+asyncpg://user:password@postgres:5432/med_scan"

    INFOCLINICA_BASE_URL: str = "https://medscan-t.infoclinica.ru"
    INFOCLINICA_TIMEOUT_SECONDS: float = 30.0
    INFOCLINICA_COOKIES: str = ""

    MAX_BOT_TOKEN: str = ""

    EXT_API_URL: str = "https://ext-api.max.ru"
    EXT_API_TOKEN: str = ""
    EXT_API_TIMEOUT_SECONDS: float = 30.0

    MAX_API_URL: str = "https://platform-api.max.ru/gov/pep"
    MAX_API_AUTH_TOKEN: str = ""
    MAX_API_TIMEOUT_SECONDS: float = 30.0

    REDIS_URL: str = "redis://:@redis:6379/0"
    CELERY_BROKER: str = REDIS_URL

    MEDIA_ROOT: str = "media"

    OPENSSL_CERT_PATH: str = "/opt/services/app/src/dev_cert.pem"
    OPENSSL_KEY_PATH: str = "/opt/services/app/src/dev_key.pem"

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
