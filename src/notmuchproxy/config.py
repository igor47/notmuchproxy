import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    api_key: str = Field(
        validation_alias="NOTMUCHPROXY_API_KEY",
        description="Bearer token clients must present in the Authorization header",
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
    return Settings()  # pyright: ignore[reportCallIssue] - fields come from the environment


def cors_origins() -> list[str]:
    """Origins allowed for CORS, from NOTMUCHPROXY_CORS_ORIGINS (comma-separated;
    '*' for any origin, empty to disable CORS entirely).

    Read directly from the environment rather than Settings because middleware
    is configured at app construction (import time), before required settings
    like the API key can be assumed to validate.
    """
    raw = os.environ.get("NOTMUCHPROXY_CORS_ORIGINS", "*")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
