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


@lru_cache
def get_settings() -> Settings:
    return Settings()  # pyright: ignore[reportCallIssue] - fields come from the environment
