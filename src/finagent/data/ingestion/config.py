from __future__ import annotations

import os
import stat
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .akshare import AKShareMarketDataIngestor
from .alpaca import AlpacaMarketDataIngestor
from .hithink import HiThinkMarketDataIngestor
from .provider import ProviderSymbolMap
from .tushare import TushareMarketDataIngestor


@dataclass(frozen=True, slots=True)
class MarketDataProfile:
    """Public market-data routing configuration. Credentials are never stored here."""

    name: str
    provider: str
    secret_id: str | None = None

    def __post_init__(self) -> None:
        name = self.name.strip()
        provider = self.provider.strip().lower()
        secret_id = None if self.secret_id is None else self.secret_id.strip() or None
        if not name:
            raise ValueError("market-data profile name is required")
        if provider not in {"alpaca", "akshare", "tushare", "hithink"}:
            raise ValueError(f"unsupported market-data provider: {provider}")
        if provider != "akshare" and secret_id is None:
            raise ValueError(f"market-data provider {provider!r} requires secret_id")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "secret_id", secret_id)


@dataclass(frozen=True, slots=True)
class ConfiguredMarketData:
    """Host-side provider binding without credential values in the public profile."""

    profile: MarketDataProfile
    ingestor: object = field(repr=False)


def _read_toml(path: Path) -> Mapping[str, object]:
    try:
        with path.open("rb") as handle:
            payload = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"market-data configuration file not found: {path}") from exc
    if not isinstance(payload, dict):
        raise TypeError(f"TOML document must contain a table: {path}")
    return payload


def _market_data_table(config_path: Path) -> Mapping[str, object]:
    payload = _read_toml(config_path)
    table = payload.get("market_data")
    if not isinstance(table, dict):
        raise TypeError("market-data configuration must contain [market_data]")
    return table


def load_market_data_profile(
    config_path: str | Path,
    profile_name: str | None = None,
) -> MarketDataProfile:
    """Load provider routing without touching any credential file."""

    path = Path(config_path).expanduser()
    market_data = _market_data_table(path)
    selected = str(profile_name or market_data.get("default_profile", "")).strip()
    if not selected:
        raise ValueError("[market_data].default_profile or an explicit profile_name is required")
    profiles = market_data.get("profiles")
    if not isinstance(profiles, dict):
        raise TypeError("market-data configuration must contain [market_data.profiles.*] tables")
    values = profiles.get(selected)
    if not isinstance(values, dict):
        raise KeyError(f"market-data profile not found: {selected}")

    forbidden = {"api_key", "secret_key", "token", "password", "api_secret"}
    leaked_fields = sorted(forbidden.intersection(str(key).lower() for key in values))
    if leaked_fields:
        raise ValueError(
            "credentials must not be stored in public market-data profiles: "
            + ", ".join(leaked_fields)
        )

    provider = str(values.get("provider", "")).strip().lower()
    secret_raw = values.get("secret_id")
    secret_id = None if secret_raw is None else str(secret_raw).strip() or None
    return MarketDataProfile(name=selected, provider=provider, secret_id=secret_id)


def _configured_secrets_path(
    *,
    market_data: Mapping[str, object],
    explicit_path: str | Path | None,
) -> Path:
    if explicit_path is not None:
        return Path(explicit_path).expanduser()
    environment_path = os.environ.get("FINAGENT_SECRETS_FILE", "").strip()
    if environment_path:
        return Path(environment_path).expanduser()
    configured = str(
        market_data.get("secrets_file", "~/.config/finagent/secrets.toml")
    ).strip()
    if not configured:
        raise ValueError("[market_data].secrets_file cannot be empty")
    return Path(configured).expanduser()


def _assert_private_secret_file(path: Path, *, enforce: bool) -> None:
    if not enforce or os.name != "posix":
        return
    permissions = stat.S_IMODE(path.stat().st_mode)
    if permissions & 0o077:
        raise PermissionError(
            f"FinAgent secret file permissions are too broad: {path}; run chmod 600 on the file"
        )


def _read_credential_table(
    *,
    secret_path: Path,
    secret_id: str,
    enforce_private_permissions: bool,
) -> Mapping[str, object]:
    if not secret_path.is_file():
        raise FileNotFoundError(f"FinAgent secret file not found: {secret_path}")
    _assert_private_secret_file(secret_path, enforce=enforce_private_permissions)
    payload = _read_toml(secret_path)
    credentials = payload.get("market_credentials")
    if not isinstance(credentials, dict):
        raise TypeError("secret file must contain [market_credentials.*] for paid data providers")
    values = credentials.get(secret_id)
    if not isinstance(values, dict):
        raise KeyError(f"market-data secret_id is not configured: {secret_id}")
    return values


def _required_secret(values: Mapping[str, object], name: str, secret_id: str) -> str:
    value = str(values.get(name, "")).strip()
    if not value:
        raise KeyError(f"market-data credential {secret_id}.{name} is not configured")
    return value


def load_configured_market_data(
    config_path: str | Path,
    *,
    profile_name: str | None = None,
    secrets_path: str | Path | None = None,
    symbol_map: ProviderSymbolMap | None = None,
) -> ConfiguredMarketData:
    """Construct a market-data ingestor at the host boundary.

    Secret values are read only when the selected provider requires credentials and
    are never attached to MarketDataProfile, pull requests, manifests, or metadata.
    AKShare is credential-free and therefore does not touch the secret file.
    """

    path = Path(config_path).expanduser()
    market_data = _market_data_table(path)
    profile = load_market_data_profile(path, profile_name)

    if profile.provider == "akshare":
        try:
            import akshare as ak
        except ImportError as exc:
            raise RuntimeError("AKShare support is optional; install the cn-free extra") from exc
        return ConfiguredMarketData(
            profile=profile,
            ingestor=AKShareMarketDataIngestor(ak, symbol_map=symbol_map),
        )

    assert profile.secret_id is not None
    secret_path = _configured_secrets_path(
        market_data=market_data,
        explicit_path=secrets_path,
    )
    enforce_permissions = bool(market_data.get("enforce_private_secret_file", True))
    credentials = _read_credential_table(
        secret_path=secret_path,
        secret_id=profile.secret_id,
        enforce_private_permissions=enforce_permissions,
    )

    ingestor: object
    if profile.provider == "alpaca":
        api_key = _required_secret(credentials, "api_key", profile.secret_id)
        secret_key = _required_secret(credentials, "secret_key", profile.secret_id)
        try:
            from alpaca.data.historical import StockHistoricalDataClient
        except ImportError as exc:
            raise RuntimeError("Alpaca support is optional; install the us-market extra") from exc
        ingestor = AlpacaMarketDataIngestor(StockHistoricalDataClient(api_key, secret_key))
    elif profile.provider == "tushare":
        token = _required_secret(credentials, "token", profile.secret_id)
        try:
            import tushare as ts
        except ImportError as exc:
            raise RuntimeError("Tushare support is optional; install the a-share extra") from exc
        ingestor = TushareMarketDataIngestor(ts.pro_api(token))
    else:
        api_key = _required_secret(credentials, "api_key", profile.secret_id)
        ingestor = HiThinkMarketDataIngestor(api_key)

    return ConfiguredMarketData(profile=profile, ingestor=ingestor)
