from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "AfriTrust API"
    VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/v1"

    DATABASE_URL: str = "sqlite+aiosqlite:///./afritrust.db"
    DATABASE_SSL: bool = False

    JWT_SECRET_KEY: str = "CHANGE-ME-IN-PRODUCTION"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    API_KEY_PEPPER: str = "CHANGE-ME-pepper"

    CORS_ORIGINS: str = "*"
    ENVIRONMENT: str = "development"

    STORAGE_BACKEND: str = "local"
    UPLOAD_DIR: str = "uploads"

    S3_BUCKET: Optional[str] = None
    S3_REGION: Optional[str] = None
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None

    model_config = {"env_file": ".env", "case_sensitive": True}


settings = Settings()
