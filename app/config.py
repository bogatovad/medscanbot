from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DB_URL: str = "postgresql+asyncpg://user:password@postgres:5432/med_scan"

    INFOCLINICA_BASE_URL: str = "https://demo.infoclinica.ru"
    INFOCLINICA_TIMEOUT_SECONDS: float = 30.0
    INFOCLINICA_COOKIES: str = ""

    MAX_BOT_TOKEN: str = ""

    model_config = SettingsConfigDict(env_file="../.env")


settings = Settings()
