from __future__ import annotations

import importlib.util
import os
import stat
import sys
import types
from pathlib import Path

import pytest

from finagent.data import load_configured_market_data, load_market_data_profile


def _write_public_config(path: Path, *, provider: str = "alpaca") -> None:
    secret_line = "" if provider == "akshare" else f'secret_id = "{provider}"\n'
    path.write_text(
        "[market_data]\n"
        'default_profile = "test"\n'
        'secrets_file = "unused.toml"\n'
        "enforce_private_secret_file = true\n\n"
        "[market_data.profiles.test]\n"
        f'provider = "{provider}"\n'
        f"{secret_line}",
        encoding="utf-8",
    )


def _load_validate_script():
    script = Path(__file__).resolve().parents[1] / "scripts" / "validate_market_data.py"
    spec = importlib.util.spec_from_file_location("finagent_validate_market_data_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_market_profile_contains_no_credentials(tmp_path):
    config = tmp_path / "market_data.toml"
    _write_public_config(config)
    profile = load_market_data_profile(config)
    rendered = repr(profile)
    assert profile.provider == "alpaca"
    assert profile.secret_id == "alpaca"
    assert "api_key" not in rendered
    assert "secret_key" not in rendered


def test_public_market_profile_rejects_inline_credentials(tmp_path):
    config = tmp_path / "market_data.toml"
    config.write_text(
        "[market_data]\n"
        'default_profile = "bad"\n\n'
        "[market_data.profiles.bad]\n"
        'provider = "alpaca"\n'
        'secret_id = "alpaca"\n'
        'api_key = "must-not-be-here"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="credentials must not be stored"):
        load_market_data_profile(config)


def test_alpaca_factory_uses_host_secret_without_exposing_it(tmp_path, monkeypatch):
    config = tmp_path / "market_data.toml"
    _write_public_config(config)
    secrets = tmp_path / "secrets.toml"
    secrets.write_text(
        "[market_credentials.alpaca]\n"
        'api_key = "alpaca-test-key"\n'
        'secret_key = "alpaca-test-secret"\n',
        encoding="utf-8",
    )
    if os.name == "posix":
        secrets.chmod(0o600)

    captured: dict[str, str] = {}

    class FakeClient:
        def __init__(self, api_key: str, secret_key: str) -> None:
            captured["api_key"] = api_key
            captured["secret_key"] = secret_key

    alpaca = types.ModuleType("alpaca")
    data = types.ModuleType("alpaca.data")
    historical = types.ModuleType("alpaca.data.historical")
    alpaca.__path__ = []
    data.__path__ = []
    historical.StockHistoricalDataClient = FakeClient
    alpaca.data = data
    data.historical = historical
    monkeypatch.setitem(sys.modules, "alpaca", alpaca)
    monkeypatch.setitem(sys.modules, "alpaca.data", data)
    monkeypatch.setitem(sys.modules, "alpaca.data.historical", historical)

    configured = load_configured_market_data(config, secrets_path=secrets)
    assert captured == {
        "api_key": "alpaca-test-key",
        "secret_key": "alpaca-test-secret",
    }
    assert "alpaca-test-key" not in repr(configured)
    assert "alpaca-test-secret" not in repr(configured)
    assert configured.profile.provider == "alpaca"


def test_missing_paid_provider_secret_fails_before_sdk_import(tmp_path):
    config = tmp_path / "market_data.toml"
    _write_public_config(config)
    with pytest.raises(FileNotFoundError, match="secret file not found"):
        load_configured_market_data(config, secrets_path=tmp_path / "missing.toml")


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits only")
def test_market_secret_permissions_fail_closed(tmp_path):
    config = tmp_path / "market_data.toml"
    _write_public_config(config)
    secrets = tmp_path / "secrets.toml"
    secrets.write_text(
        "[market_credentials.alpaca]\n"
        'api_key = "x"\n'
        'secret_key = "y"\n',
        encoding="utf-8",
    )
    secrets.chmod(0o644)
    assert stat.S_IMODE(secrets.stat().st_mode) == 0o644
    with pytest.raises(PermissionError, match="chmod 600"):
        load_configured_market_data(config, secrets_path=secrets)


def test_akshare_profile_does_not_require_secret_file(tmp_path, monkeypatch):
    config = tmp_path / "market_data.toml"
    _write_public_config(config, provider="akshare")
    fake_akshare = types.ModuleType("akshare")
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)
    configured = load_configured_market_data(
        config,
        secrets_path=tmp_path / "definitely-missing.toml",
    )
    assert configured.profile.provider == "akshare"


def test_validate_market_data_accepts_materialized_directory(tmp_path):
    module = _load_validate_script()
    materialized = tmp_path / "market"
    materialized.mkdir()
    bars = materialized / "bars.csv"
    bars.write_text("header\n", encoding="utf-8")
    assert module._resolve_bars_path(materialized) == bars
    assert module._resolve_bars_path(bars) == bars


def test_validate_market_data_reports_missing_pull_output(tmp_path):
    module = _load_validate_script()
    with pytest.raises(FileNotFoundError, match="run pull_market_data.py successfully"):
        module._resolve_bars_path(tmp_path / "missing-market-data")
