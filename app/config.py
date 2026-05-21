from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str
    redis_url: str
    dedup_window_seconds: int = 300
    app_env: str = "development"

    class Config:
        env_file = ".env"

settings = Settings()