"""Settings, read from the environment (KASITA_*)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KASITA_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./kasita.db"
    # signs access/refresh tokens; must be long and random in production
    secret_key: str = "change-me"
    public_url: str = "http://localhost:8000"
    access_token_minutes: int = 60
    refresh_token_days: int = 90
    # contact address sent to Open Food Facts in the User-Agent, as their API asks
    off_contact: str = "kasita-selfhosted"
    # how long a barcode lookup result (found or not found) is trusted before asking again
    barcode_cache_days: int = 30
    upload_dir: str = "./uploads"
    # run Alembic migrations on startup
    auto_migrate: bool = True
    # receipts: longest side of the stored/sent photo, and the ChatGPT models to prefer (first available wins)
    receipt_max_px: int = 2400
    # long receipts (several parts, or a panorama): strip width, and a sanity cap on its height
    receipt_strip_width: int = 1400
    receipt_strip_max_height: int = 20000
    chatgpt_models: str = "gpt-5.6-sol,gpt-5.6,gpt-5.5,gpt-5.4,gpt-5.4-mini"
    # Flutter web build to serve at /, if present
    web_dir: str = "./web"


settings = Settings()
