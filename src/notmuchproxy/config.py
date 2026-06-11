import os
from functools import lru_cache

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    api_key: str | None = Field(
        default=None,
        validation_alias="NOTMUCHPROXY_API_KEY",
        description=(
            "static bearer token clients must present in the Authorization header; "
            "mutually exclusive with the OIDC settings"
        ),
    )
    notmuch_database: str | None = Field(
        default=None,
        validation_alias="NOTMUCH_DATABASE",
        description="Path to the notmuch database root (the directory containing .notmuch)",
    )
    notmuch_bin: str = Field(
        default="notmuch",
        validation_alias="NOTMUCHPROXY_NOTMUCH_BIN",
        description="notmuch executable to invoke",
    )
    exclude_tags: str = Field(
        default="",
        validation_alias="NOTMUCHPROXY_EXCLUDE_TAGS",
        description=(
            "comma-separated tags whose messages are excluded from all results, "
            "even when queried explicitly (e.g. 'spam,deleted')"
        ),
    )

    @property
    def exclude_tag_list(self) -> list[str]:
        return [tag.strip() for tag in self.exclude_tags.split(",") if tag.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


class OidcConfig(BaseModel):
    config_url: str
    client_id: str
    client_secret: str
    public_url: str


_OIDC_VARS = {
    "config_url": "NOTMUCHPROXY_OIDC_CONFIG_URL",
    "client_id": "NOTMUCHPROXY_OIDC_CLIENT_ID",
    "client_secret": "NOTMUCHPROXY_OIDC_CLIENT_SECRET",
    "public_url": "NOTMUCHPROXY_PUBLIC_URL",
}


def oidc_config() -> OidcConfig | None:
    """OIDC auth settings; setting any of the four vars requires all of them.

    Read directly from the environment (like cors_origins) because the auth
    provider is constructed at import time.
    """
    values = {field: os.environ.get(var, "") for field, var in _OIDC_VARS.items()}
    if not any(values.values()):
        return None
    if missing := [var for field, var in _OIDC_VARS.items() if not values[field]]:
        raise RuntimeError(f"incomplete OIDC config; also set: {', '.join(missing)}")
    return OidcConfig(**values)


def check_auth_config() -> None:
    """Exactly one auth mechanism must be configured; called at startup."""
    oidc = oidc_config()  # raises if partially configured
    api_key = os.environ.get("NOTMUCHPROXY_API_KEY", "")
    if oidc and api_key:
        raise RuntimeError(
            "both NOTMUCHPROXY_API_KEY and OIDC settings are set; pick one auth mechanism"
        )
    if not oidc and not api_key:
        raise RuntimeError(
            "no auth configured: set NOTMUCHPROXY_API_KEY (static bearer) or the "
            f"OIDC settings ({', '.join(_OIDC_VARS.values())})"
        )


def cors_origins() -> list[str]:
    """Origins allowed for CORS, from NOTMUCHPROXY_CORS_ORIGINS (comma-separated;
    '*' for any origin, empty to disable CORS entirely).

    Read directly from the environment rather than Settings because middleware
    is configured at app construction (import time), before required settings
    like the API key can be assumed to validate.
    """
    raw = os.environ.get("NOTMUCHPROXY_CORS_ORIGINS", "*")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
