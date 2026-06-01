"""Configuration discovery, loading, and validation."""

import os
import sys
from pathlib import Path

import yaml

from mewcode.config.models import AppConfig, ProviderConfig

# Default base URLs per protocol
DEFAULT_BASE_URLS: dict[str, str] = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com",
    "deepseek": "https://api.deepseek.com",
}

# Protocol values that are recognized
SUPPORTED_PROTOCOLS = {"anthropic", "openai", "deepseek"}


def _resolve_config_path() -> Path | None:
    """Resolve the config file path using three-tier discovery.

    Priority (highest first):
        1. Environment variable ``MEWCODE_CONFIG``
        2. ``.mewcode.yaml`` in current directory
        3. ``~/.mewcode/config.yaml``
    """
    env_path = os.environ.get("MEWCODE_CONFIG")
    if env_path:
        return Path(env_path)

    cwd_path = Path.cwd() / ".mewcode.yaml"
    if cwd_path.exists():
        return cwd_path

    home_path = Path.home() / ".mewcode" / "config.yaml"
    if home_path.exists():
        return home_path

    return None


def _validate_provider(provider: dict, index: int) -> ProviderConfig:
    """Validate a single provider entry and return a ProviderConfig."""
    name = provider.get("name", f"provider-{index}")
    protocol = provider.get("protocol")
    model = provider.get("model")
    api_key = provider.get("api_key")

    if not protocol:
        print(f"Provider '{name}' 缺少字段: protocol", file=sys.stderr)
        sys.exit(1)
    if protocol not in SUPPORTED_PROTOCOLS:
        print(f"不支持的协议: {protocol}", file=sys.stderr)
        sys.exit(1)
    if not model:
        print(f"Provider '{name}' 缺少字段: model", file=sys.stderr)
        sys.exit(1)
    if not api_key:
        print(f"Provider '{name}' 缺少 api_key", file=sys.stderr)
        sys.exit(1)

    base_url = provider.get("base_url") or DEFAULT_BASE_URLS.get(protocol, "")

    return ProviderConfig(
        name=name,
        protocol=protocol,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )


def load_config() -> AppConfig:
    """Discover, load, parse, and validate the YAML configuration.

    Returns:
        AppConfig: Validated application configuration.

    Exits the process with an error message if the config is missing or invalid.
    """
    config_path = _resolve_config_path()

    if config_path is None:
        print("配置文件缺失: 请在当前目录创建 .mewcode.yaml，或在 ~/.mewcode/config.yaml 放置全局配置", file=sys.stderr)
        sys.exit(1)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"配置文件解析失败 ({config_path}): {e}", file=sys.stderr)
        sys.exit(1)

    if raw is None or "providers" not in raw:
        print("配置文件缺少 'providers' 字段", file=sys.stderr)
        sys.exit(1)

    providers = [_validate_provider(p, i) for i, p in enumerate(raw["providers"])]

    provider_names = [p.name for p in providers]
    active_provider = raw.get("active_provider")
    if active_provider is None:
        active_provider = provider_names[0]
    if active_provider not in provider_names:
        print(
            f"active_provider '{active_provider}' 不在 providers 列表中（可用: {', '.join(provider_names)}）",
            file=sys.stderr,
        )
        sys.exit(1)

    return AppConfig(providers=providers, active_provider=active_provider)
