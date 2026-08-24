"""Typed application settings loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings sourced from `.env` / the process environment."""

    # `.env` also carries POSTGRES_* keys that only docker-compose.yml reads
    # (to stay in sync with the credentials embedded in DATABASE_URL) — this
    # class doesn't need them as fields, so unrecognized keys are ignored
    # instead of raising.
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    log_level: str = "INFO"

    # No defaults for these: a missing value must fail Settings()
    # construction immediately. `environment` isn't branched on yet, but
    # once it is (e.g. gating debug behavior), silently defaulting to
    # "development" could mask a real production misconfiguration —
    # connection strings and origins have the same silent-failure risk.
    environment: str
    cors_origins: str
    database_url: str
    # The running API's own connection identity from Phase 8 onward: the
    # least-privilege `obur_app` role, never the owner role `database_url`
    # connects as (migrations, the seeder). See ADR-0016 in obur-docs.
    # Deliberately a separate setting, not derived from `database_url`: an
    # owner-role connection string with the app role's credentials spliced
    # in would silently reintroduce the single-role setup this exists to
    # replace the moment someone forgot to change it back.
    app_database_url: str
    redis_url: str
    # Genuinely consumed now (app/core/security.py) — required as of Phase 1.
    clerk_secret_key: str

    # Keys the anonymous rate-limit counter (app/middleware/rate_limit.py).
    # Required, and no default: without a secret the derivation is a plain
    # hash of a space small enough to enumerate exhaustively, which makes the
    # stored value reversible — see ADR-0014 in obur-docs.
    rate_limit_secret: str

    # How many reverse proxies sit between the internet and this process, and
    # therefore how many entries to skip from the right of `X-Forwarded-For`
    # before the value stops being client-controlled. No default on purpose:
    # a wrong value disables rate limiting silently rather than failing, so it
    # has to be stated for each deployment. 0 locally, where nothing proxies.
    trusted_proxy_count: int

    # Not required yet: the webhook endpoint (app/api/v1/webhooks.py) is
    # built and unit-tested, but real Clerk webhook delivery needs a public
    # URL to register in the Clerk Dashboard, which doesn't exist until
    # closer to deployment. Make this required once that's configured.
    clerk_webhook_secret: str = ""

    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = ""
    r2_endpoint_url: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse the comma-separated `cors_origins` setting into a list."""
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached `Settings` instance."""
    # Required fields are loaded from the environment at runtime by
    # pydantic-settings, not passed as constructor arguments — pyright can't
    # see that, so it flags this call as missing arguments.
    return Settings()  # pyright: ignore[reportCallIssue]
