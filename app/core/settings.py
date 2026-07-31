from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """应用配置。"""

    app_name: str = "Darwin Knowledge Platform"
    app_env: Literal["development", "test", "production"] = "development"
    app_debug: bool = False
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    docs_url: str = "/docs"
    redoc_url: str = "/redoc"

    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_name: str
    db_user: str
    db_password: SecretStr

    jwt_secret_key: SecretStr
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_access_token_expire_minutes: int = Field(default=120, gt=0)

    openclaw_base_url: str = "http://127.0.0.1:18789"
    openclaw_gateway_token: SecretStr = SecretStr("")
    openclaw_timeout_seconds: float = Field(default=20, gt=0)

    snowflake_worker_id: int = Field(default=1, ge=0, le=1023)
    snowflake_epoch_ms: int = Field(default=1767225600000, gt=0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("openclaw_base_url")
    @classmethod
    def normalize_openclaw_base_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        if not normalized:
            raise ValueError("openclaw_base_url cannot be empty")
        return normalized

    @property
    def database_url(self) -> URL:
        """构造可安全处理保留字符的 SQLAlchemy 数据库 URL。"""

        return URL.create(
            drivername="mysql+asyncmy",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query={"charset": "utf8mb4"},
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
