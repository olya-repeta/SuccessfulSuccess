"""Application settings, loaded from the environment."""

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql+asyncpg://app:app@db:5432/meetings"
    app_timezone: str = "Europe/Kyiv"
    cors_origins: str = "http://localhost:3000"
    log_level: str = "INFO"
    run_migrations_on_start: bool = True
    version: str = Field(default="1.0.0")

    # LLM parser model for Bedrock Mantle
    parser_model: str = Field(
        default="anthropic.claude-opus-5-5",
        validation_alias=AliasChoices("PARSER_MODEL", "parser_model"),
    )

    # Cognito user pool whose access tokens the API accepts. Empty pool id means
    # authentication is not configured, and every meetings request is refused.
    cognito_region: str = "us-east-1"
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    # The pool's signing keys (JSON, or that JSON base64-encoded). The Lambda
    # runs in a VPC without internet access, so the deploy passes them in; when
    # empty they are fetched from Cognito on first use.
    cognito_jwks: str = ""

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        return value.strip()

    @field_validator("app_timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        ZoneInfo(value)  # raises for an unknown timezone
        return value

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @property
    def cognito_issuer(self) -> str:
        return (
            f"https://cognito-idp.{self.cognito_region}.amazonaws.com/{self.cognito_user_pool_id}"
        )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def PARSER_MODEL(self) -> str:
        return self.parser_model


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
