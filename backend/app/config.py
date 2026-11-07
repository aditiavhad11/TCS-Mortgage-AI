from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET = "development-only-change-me"
MIN_PASSWORD_LENGTH = 8          # single source of truth for every account type
MIN_PBKDF2_ITERATIONS_PROD = 210_000

class Settings(BaseSettings):
    app_name: str = "TCS Mortgage AI"
    environment: str = "development"
    database_url: str = "sqlite:///./mortgage.db"
    frontend_origin: str = "http://127.0.0.1:5173"
    jwt_secret_key: str = DEFAULT_SECRET
    access_token_minutes: int = 60
    otp_expiry_minutes: int = 10
    otp_resend_cooldown_seconds: int = 60
    password_reset_expiry_minutes: int = 30
    max_upload_size_mb: int = 15
    uploads_dir: str = "./private_uploads"
    tesseract_cmd: str = ""
    ocr_max_pages: int = 30
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "nvidia/nemotron-3.5-lightning-30b-a3b"
    nvidia_embed_model: str = "nvidia/nemotron-3-embed-1b"
    nvidia_timeout_seconds: int = 45
    nemotron_max_input_chars: int = 24000
    nemotron_disable_thinking: bool = True  # ask NVIDIA to skip the reasoning phase for fast structured extraction
    financial_tolerance_percent: float = 2.0
    login_max_failures: int = 5
    login_lockout_minutes: int = 15
    initial_admin_name: str = ""
    initial_admin_email: str = ""
    # Password hashing: PBKDF2-HMAC-SHA256. OWASP (2023) recommends >= 600,000 iterations.
    pbkdf2_iterations: int = 600_000
    # Retained for backward-compatible configuration parsing; Platform Admin OTP is always required.
    admin_otp_required: bool = True
    # Optional SMTP delivery for OTP emails. Without it, OTPs are only printed to the console in development.
    smtp_host: str = Field(default="", validation_alias=AliasChoices("SMTP_HOST", "EMAIL_HOST"))
    smtp_port: int = Field(default=587, validation_alias=AliasChoices("SMTP_PORT", "EMAIL_PORT"))
    smtp_username: str = Field(default="", validation_alias=AliasChoices("SMTP_USERNAME", "SMTP_USER", "EMAIL_USER"))
    smtp_password: str = Field(default="", validation_alias=AliasChoices("SMTP_PASSWORD", "EMAIL_APP_PASSWORD"))
    smtp_from: str = Field(default="", validation_alias=AliasChoices("SMTP_FROM", "EMAIL_FROM"))
    frontend_base_url: str = "http://localhost:5173"  # used in emailed links (bank admin invitation)
    # Seconds between background retries of applications awaiting reviewer assignment (0 disables the loop).
    assignment_retry_interval_seconds: int = 60
    smtp_use_ssl: bool = Field(default=False, validation_alias=AliasChoices("SMTP_USE_SSL", "EMAIL_SECURE"))       # True = implicit TLS (usually port 465); False = STARTTLS
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()

def validate_runtime(s: Settings = settings) -> None:
    """Refuse to start outside development with a weak/default JWT secret."""
    if s.environment.lower() != "development" and (s.jwt_secret_key == DEFAULT_SECRET or s.jwt_secret_key.startswith("replace-with") or len(s.jwt_secret_key) < 32):
        raise RuntimeError("JWT_SECRET_KEY must be a random value of at least 32 characters when ENVIRONMENT is not 'development'.")
    if s.environment.lower() != "development":
        if s.pbkdf2_iterations < MIN_PBKDF2_ITERATIONS_PROD:
            raise RuntimeError(f"PBKDF2_ITERATIONS must be at least {MIN_PBKDF2_ITERATIONS_PROD} when ENVIRONMENT is not 'development'.")
        if not s.smtp_host:
            raise RuntimeError("Platform Admin OTP is required but no delivery channel is configured. Set SMTP_HOST (and related SMTP_* values).")
