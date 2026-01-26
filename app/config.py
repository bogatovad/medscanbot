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

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
