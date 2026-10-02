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
    llm_provider: str = "rules"            # "rules" (no AI) or "anthropic"
    anthropic_api_key: str = ""
    anthropic_workspace_id: str = ""       # only if your key is not scoped to a workspace (sent as anthropic-workspace-id)
    ai_model: str = "claude-opus-5-5"      # e.g. claude-sonnet-5-5 for lower cost
    ai_timeout_seconds: float = 120.0
    ai_max_fit_calls_per_run: int = 40     # job-fit scoring calls per search run (cached results are free)
    ai_max_tailor_per_run: int = 10        # AI-tailored resumes per search run
    ai_min_rules_score: float = 10.0       # jobs scoring below this on rules alone are not sent to the AI
    ai_blend_weight: float = 0.65          # share of the final score that comes from the AI fit score
    ai_max_job_chars: int = 12000          # job text truncation sent to the model
    ai_verify_tailoring: bool = True       # second AI pass that audits rewritten bullets for unsupported claims
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
