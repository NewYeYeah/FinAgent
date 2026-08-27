from __future__ import annotations

import os
import stat
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .base import LLMProvider
from .openai import OpenAIResponsesProvider
from .openai_compatible import DeepSeekChatProvider, SiliconFlowChatProvider


@dataclass(frozen=True, slots=True)
class LLMProfile:
    """Public LLM routing configuration. This object never contains credentials."""

    name: str
    provider: str
    model: str
    secret_id: str
    base_url: str | None = None
    thinking: bool | None = None
    reasoning_effort: str | None = None
    max_attempts: int = 3
    retry_backoff_seconds: float = 1.0
    timeout_seconds: float = 900.0

    def __post_init__(self) -> None:
        for field_name in ("name", "provider", "model", "secret_id"):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} is required")
            object.__setattr__(self, field_name, value)
        provider = self.provider.lower()
        if provider not in {"deepseek", "siliconflow", "openai"}:
            raise ValueError(f"unsupported LLM provider: {provider}")
        object.__setattr__(self, "provider", provider)
        if self.reasoning_effort is not None and self.reasoning_effort not in {
            "low",
            "high",
            "max",
        }:
            raise ValueError("reasoning_effort must be one of: low, high, max")
        if isinstance(self.max_attempts, bool) or self.max_attempts < 1:
            raise ValueError("max_attempts must be an integer >= 1")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be >= 0")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")


@dataclass(frozen=True, slots=True)
class ConfiguredLLM:
    """Host-side provider binding exposed to the application without the secret value."""

    profile: LLMProfile
    provider: LLMProvider = field(repr=False)

    @property
    def model(self) -> str:
        return self.profile.model


def _read_toml(path: Path) -> Mapping[str, object]:
    try:
        with path.open("rb") as handle:
            payload = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"LLM configuration file not found: {path}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"TOML document must contain a table: {path}")
    return payload


def _llm_table(config_path: Path) -> Mapping[str, object]:
    payload = _read_toml(config_path)
    llm = payload.get("llm")
    if not isinstance(llm, dict):
        raise TypeError("LLM configuration must contain [llm]")
    return llm


def load_llm_profile(config_path: str | Path, profile_name: str | None = None) -> LLMProfile:
    """Load public routing/model configuration without touching the secret file."""

    path = Path(config_path).expanduser()
    llm = _llm_table(path)
    selected = str(profile_name or llm.get("default_profile", "")).strip()
    if not selected:
        raise ValueError("[llm].default_profile or an explicit profile_name is required")
    profiles = llm.get("profiles")
    if not isinstance(profiles, dict):
        raise TypeError("LLM configuration must contain [llm.profiles.*] tables")
    values = profiles.get(selected)
    if not isinstance(values, dict):
        raise KeyError(f"LLM profile not found: {selected}")

    provider = str(values.get("provider", "")).strip().lower()
    model = str(values.get("model", "")).strip()
    secret_id = str(values.get("secret_id", "")).strip()
    base_url_raw = values.get("base_url")
    base_url = None if base_url_raw is None else str(base_url_raw).strip() or None
    thinking_raw = values.get("thinking")
    if thinking_raw is not None and not isinstance(thinking_raw, bool):
        raise TypeError(f"llm.profiles.{selected}.thinking must be a boolean")
    reasoning_raw = values.get("reasoning_effort")
    reasoning_effort = None if reasoning_raw is None else str(reasoning_raw).strip() or None
    max_attempts = int(values.get("max_attempts", 3))
    retry_backoff_seconds = float(values.get("retry_backoff_seconds", 1.0))
    timeout_seconds = float(values.get("timeout_seconds", 900.0))

    return LLMProfile(
        name=selected,
        provider=provider,
        model=model,
        secret_id=secret_id,
        base_url=base_url,
        thinking=thinking_raw,
        reasoning_effort=reasoning_effort,
        max_attempts=max_attempts,
        retry_backoff_seconds=retry_backoff_seconds,
        timeout_seconds=timeout_seconds,
    )


def _configured_secrets_path(
    *,
    llm: Mapping[str, object],
    explicit_path: str | Path | None,
) -> Path:
    if explicit_path is not None:
        return Path(explicit_path).expanduser()
    environment_path = os.environ.get("FINAGENT_SECRETS_FILE", "").strip()
    if environment_path:
        return Path(environment_path).expanduser()
    configured = str(llm.get("secrets_file", "~/.config/finagent/secrets.toml")).strip()
    if not configured:
        raise ValueError("[llm].secrets_file cannot be empty")
    return Path(configured).expanduser()


def _assert_private_secret_file(path: Path, *, enforce: bool) -> None:
    if not enforce or os.name != "posix":
        return
    permissions = stat.S_IMODE(path.stat().st_mode)
    if permissions & 0o077:
        raise PermissionError(
            f"LLM secret file permissions are too broad: {path}; run chmod 600 on the file"
        )


def _read_api_key(
    *,
    secret_path: Path,
    secret_id: str,
    enforce_private_permissions: bool,
) -> str:
    if not secret_path.is_file():
        raise FileNotFoundError(f"LLM secret file not found: {secret_path}")
    _assert_private_secret_file(secret_path, enforce=enforce_private_permissions)
    payload = _read_toml(secret_path)
    api_keys = payload.get("api_keys")
    if not isinstance(api_keys, dict):
        raise TypeError("LLM secret file must contain [api_keys]")
    api_key = str(api_keys.get(secret_id, "")).strip()
    if not api_key:
        raise KeyError(f"API key secret_id is not configured: {secret_id}")
    return api_key


def load_configured_llm(
    config_path: str | Path,
    *,
    profile_name: str | None = None,
    secrets_path: str | Path | None = None,
) -> ConfiguredLLM:
    """Construct the configured provider at the host boundary.

    The API key exists only as a local variable long enough to construct the SDK client.
    It is never attached to the returned profile, LLMRequest, AgentTask, or metadata.
    """

    path = Path(config_path).expanduser()
    llm = _llm_table(path)
    profile = load_llm_profile(path, profile_name)
    secret_path = _configured_secrets_path(llm=llm, explicit_path=secrets_path)
    enforce_permissions = bool(llm.get("enforce_private_secret_file", True))
    api_key = _read_api_key(
        secret_path=secret_path,
        secret_id=profile.secret_id,
        enforce_private_permissions=enforce_permissions,
    )

    provider: LLMProvider
    if profile.provider == "deepseek":
        provider = DeepSeekChatProvider(
            api_key=api_key,
            base_url=profile.base_url or "https://api.deepseek.com",
            thinking=True if profile.thinking is None else profile.thinking,
            reasoning_effort=profile.reasoning_effort or "high",
            max_attempts=profile.max_attempts,
            retry_backoff_seconds=profile.retry_backoff_seconds,
            timeout_seconds=profile.timeout_seconds,
        )
    elif profile.provider == "siliconflow":
        provider = SiliconFlowChatProvider(
            api_key=api_key,
            base_url=profile.base_url or "https://api.siliconflow.cn/v1",
            max_attempts=profile.max_attempts,
            retry_backoff_seconds=profile.retry_backoff_seconds,
            timeout_seconds=profile.timeout_seconds,
        )
    else:
        provider = OpenAIResponsesProvider(api_key=api_key, base_url=profile.base_url)

    return ConfiguredLLM(profile=profile, provider=provider)
