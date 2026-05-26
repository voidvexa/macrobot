from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    fred_api_key: str = ""
    telegram_bot_token: str
    telegram_chat_id: str
    timezone: str = "America/New_York"
    log_level: str = "INFO"


settings = Settings()
