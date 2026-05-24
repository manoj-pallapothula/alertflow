from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    database_url: str
    redis_url: str
    dedup_window_seconds: int = 300
    app_env: str = "development"
    slack_webhook_url: Optional[str] = None

    class Config:
        env_file = ".env"


settings = Settings()