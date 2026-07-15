from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra='ignore', env_file=".env")

    llm_api_key: str = ""
    llm_provider: str = "anthropic"
    llm_model: str = "claude-3-5-haiku-latest"
    embedding_provider: str = ""

    database_url: str = "postgresql+psycopg2://crusty:123@localhost:5432/crusty"
    redis_url: str = "redis://localhost:6379/0"

    admin_username: str = "admin"
    admin_password: str = "admin123"
    secret_key: str = "change-me-to-random-32-char-string"

    cors_origins: str = ""

    host: str = "0.0.0.0"
    port: int = 8000

    # IANA timezone the SOP scheduler interprets start/end times in. Staff and
    # the source SOP sheet are IST, so a SOP "12:00" means 12:00 Asia/Kolkata.
    app_timezone: str = "Asia/Kolkata"

    # Daily performance report auto-send: recipient (employee name or +number)
    # and the local hour (app_timezone) to send yesterday's report at.
    daily_report_recipient: str = ""  # set DAILY_REPORT_RECIPIENT in .env (E.164, e.g. +9199...)
    daily_report_hour: int = 10

    openwa_base_url: str = "http://openwa:2785/api"
    openwa_api_key: str = ""
    openwa_session_id: str = ""
    # Stable session NAME used by the GUI connect flow. The gateway assigns a
    # UUID on create; we resolve that UUID by this name and cache it (Redis), so
    # reconnecting (or a wiped gateway) doesn't strand the configured id.
    openwa_session_name: str = "wabot"
    openwa_webhook_url: str = "http://backend:8000/webhook/whatsapp"
    # Shared secret for verifying inbound webhook HMAC (X-OpenWA-Signature).
    # When set, setup-session registers the webhook with this secret and the
    # webhook handler rejects payloads with a missing/invalid signature.
    openwa_webhook_secret: str = ""

settings = Settings()
