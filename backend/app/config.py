from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = "dev-insecure-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = "sqlite:///./jobpilot.db"
    secret_key: str = _DEV_SECRET
    access_token_minutes: int = 60 * 8
    storage_dir: str = "./storage"
    max_upload_mb: int = 5
    # Application submitters in sandbox mode never contact employers.
    sandbox_mode: bool = True
    cors_origins: list[str] = ["http://localhost:3000"]
    rate_limit_auth_per_min: int = 10
    rate_limit_default_per_min: int = 300
    llm_provider: str = "rules"
    scheduler_poll_seconds: int = 60
    redis_url: str = ""
    email_backend: str = "console"
    require_email_verification: bool = False
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/auth/google/callback"  # must match the Google console exactly
    frontend_url: str = "http://localhost:3000"
    lock_ttl_seconds: int = 3600
    max_task_retries: int = 3
    retry_base_seconds: float = 1.0
    http_timeout_seconds: float = 20.0
    user_agent: str = "JobPilot/0.1 (+personal job search assistant)"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.env == "production" and s.secret_key == _DEV_SECRET:
        raise RuntimeError("SECRET_KEY must be set in production")
    return s
