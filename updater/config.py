from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    fred_api_key: str = ""
    sqlite_db_path: str = "data/macrobot.db"
    log_level: str = "INFO"


settings = Settings()
