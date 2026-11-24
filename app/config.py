from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from the environment / `.env`."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    keitaro_url: str = "https://keitaro-for-tests.etolegko.com/admin_api/v1"
    keitaro_api_key: SecretStr
    keitaro_admin_url: str = "https://keitaro-for-tests.etolegko.com/admin"
    keitaro_timeout: float = 15.0

    default_domain_id: int = 1813
    default_group_id: int = 10332
    default_source_id: int = 836
    geo_redirect_url: str = "https://google.com"

    offers_cache_ttl: int = 3600
    reference_cache_ttl: int = 3600
    # How many campaigns are pulled for a name search (the API has no server-side search).
    campaign_search_limit: int = 500

    database_url: str = "postgresql+asyncpg://adrobot:adrobot@localhost:5432/adrobot"
    log_level: str = "INFO"

    def campaign_admin_link(self, campaign_id: int) -> str:
        return f"{self.keitaro_admin_url.rstrip('/')}/#!/campaign.editor/{campaign_id}"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
