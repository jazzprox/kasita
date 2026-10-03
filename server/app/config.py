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
    # Kroger product API (free developer account, client-credentials grant): US groceries.
    # Empty = source skipped.
    kroger_client_id: str = ""
    kroger_client_secret: str = ""
    # upcdatabase.org free plan (100 lookups/day): last fallback. Empty = skipped.
    upcdatabase_token: str = ""
    # ntfy for the morning expiry list and the weekly spending summary. Empty = digests off.
    ntfy_url: str = ""
    ntfy_topic: str = ""
    ntfy_token: str = ""
    # Open Food Facts account for 'Share with Open Food Facts' (username, not email). Empty = off.
    off_user_id: str = ""
    off_password: str = ""
    off_write_host: str = ""  # "openfoodfacts.net" = their staging server, for testing
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
    # store map: OpenStreetMap's Nominatim finds stores from their address (max 1 request/second,
    # results cached). Empty URL = no geocoding; pins can still be placed by hand.
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    nominatim_user_agent: str = "Kasita (self-hosted) jazzprox@github"
    nominatim_country: str = "cw"
    geocode_retry_days: int = 30  # a search that found nothing is tried again after this long
    # the household's clock, for "which day was this" when a phone doesn't say (Curaçao: UTC-4, no DST)
    local_utc_offset_hours: int = -4
    # Flutter web build to serve at /, if present
    web_dir: str = "./web"


settings = Settings()
