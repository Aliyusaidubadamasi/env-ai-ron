import os
from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    DATABASE_URL: str = "postgresql+psycopg2://env_ai_ron:env_ai_ron@localhost:5432/env_ai_ron"
    MAPBOX_TOKEN: str = "your_mapbox_access_token"
    AWS_ACCESS_KEY: str = "your_aws_access_key"
    AWS_SECRET_KEY: str = "your_aws_secret_key"
    JWT_SECRET: str = "change_this_secret_key"
    APP_NAME: str = "Env-AI-Ron API"
    APP_ENV: str = "development"

    @property
    def cors_origins(self) -> list[str]:
        return ["http://localhost:3000", "http://127.0.0.1:3000"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
