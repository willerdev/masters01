from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"
    database_url: str = "postgresql+psycopg://tradeguard:tradeguard@localhost:5432/tradeguard"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    master_key: str = ""
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    cookie_secure: bool = False
    stale_quote_seconds: int = 30
    heartbeat_timeout_seconds: int = 90
    webhook_skew_seconds: int = 300
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = "TradeGuard <alerts@tradeguard.local>"
    smtp_tls: bool = True
    resend_api_key: str = ""
    resend_from: str = ""
    telegram_bot_token: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""
    metaapi_region: str = "new-york"
    public_base_url: str = "http://127.0.0.1:8000"
    seed_admin_email: str = ""
    seed_admin_password: str = ""
    seed_admin_name: str = "TradeGuard Admin"
    seed_sample_data: bool = False
    metrics_token: str = ""
    local_dev_master_key: str = "dHJhZGVndWFyZC1sb2NhbC1tYXN0ZXIta2V5LTMyYiE="

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
