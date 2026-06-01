"""Configuration data models."""

from pydantic import BaseModel


class ProviderConfig(BaseModel):
    """Configuration for a single LLM provider."""

    name: str
    protocol: str  # "anthropic" or "openai"
    model: str
    base_url: str | None = None
    api_key: str | None = None


class AppConfig(BaseModel):
    """Top-level application configuration."""

    providers: list[ProviderConfig]
    active_provider: str  # name of the provider to use
