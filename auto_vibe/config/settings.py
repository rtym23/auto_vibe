"""
Settings — AutoVibe configuration via Pydantic BaseSettings + .env.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMConfig(BaseModel):
    """LLM configuration."""
    provider: Literal["ollama", "openai", "mesh_llm", "mock"] = "ollama"
    model: str = "qwen3-8b-q4_k_m"
    base_url: str = "http://localhost:11434"
    mesh_peer_id: str | None = None
    mesh_network: str = "auto"
    api_key: str = ""
    timeout: int = 300


class ExecutorConfig(BaseModel):
    """Command executor configuration."""
    timeout: int = 30
    max_memory_mb: int = 512
    use_venv: bool = True


class MemoryConfig(BaseModel):
    """Memory configuration."""
    enabled: bool = True
    decay_rate: float = 0.95
    max_entries: int = 1000
    vault_path: str = "~/.auto_vibe/vault.json"


class CostConfig(BaseModel):
    """Cost tracking configuration."""
    enabled: bool = True
    price_per_1k_tokens: float = 0.0
    currency: str = "USD"


class StrategyConfig(BaseModel):
    """Strategy configuration."""
    default: Literal["quick", "deep", "max"] = "deep"
    max_iterations: int = 5
    quick_attempts: int = 1


class TokenConfig(BaseModel):
    """Token and context configuration."""
    max_context_tokens: int = 60000  # Context limit for local models
    checkpoint_interval: int = 3  # Save checkpoint every N iterations


class DashboardConfig(BaseModel):
    """Dashboard configuration."""
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 7891  # Changed from 7890 to avoid conflict with Mesh LLM


class Settings(BaseSettings):
    """
    Main application configuration.

    Supports:
    - .env file (default .env in project root)
    - Environment variables with AUTOVIBE_ prefix
    - YAML config for complex nested structures
    """

    model_config = SettingsConfigDict(
        env_prefix="AUTOVIBE_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # Core sections
    llm: LLMConfig = Field(default_factory=LLMConfig)
    executor: ExecutorConfig = Field(default_factory=ExecutorConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    cost: CostConfig = Field(default_factory=CostConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    tokens: TokenConfig = Field(default_factory=TokenConfig)

    # Additional settings
    config_path: str | None = Field(default=None, validation_alias="CONFIG")
    max_tokens: int = 60000  # Alias for tokens.max_context_tokens

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Settings":
        """
        Load configuration.

        Priority: .env -> environment variables -> YAML -> defaults
        """
        # Load from .env and environment variables first
        settings = cls()

        # Merge YAML config if specified
        if path is None:
            path = settings.config_path
        if path is None:
            path = os.environ.get("AUTOVIBE_CONFIG", "~/.auto_vibe/config.yaml")

        path = Path(path).expanduser()
        if path.exists():
            settings = cls._merge_yaml(path, settings)

        return settings

    @classmethod
    def _merge_yaml(cls, path: Path, settings: "Settings") -> "Settings":
        """Merge YAML settings with current ones (YAML takes priority)."""
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not data:
            return settings

        # Pydantic BaseSettings already merges env + defaults
        # Now merge YAML (it has the highest priority)
        merged = settings.model_dump()

        for key, value in data.items():
            if key in merged and isinstance(value, dict):
                merged[key].update(value)
            elif key not in merged:
                merged[key] = value

        return cls(**merged)

    def save(self, path: str | Path | None = None) -> Path:
        """Save config to YAML."""
        if path is None:
            path = os.environ.get("AUTOVIBE_CONFIG", "~/.auto_vibe/config.yaml")

        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)

        # Export to YAML, excluding sensitive fields
        import yaml
        data = self.model_dump()
        # Exclude API key from serialization
        if "llm" in data and "api_key" in data["llm"]:
            data["llm"]["api_key"] = ""
        yaml_text = yaml.dump(data, default_flow_style=False, sort_keys=False)
        path.write_text(yaml_text, encoding="utf-8")
        return path

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()
