from __future__ import annotations

from datetime import UTC, datetime

import pytest

from finagent.data.us_instruments import materialize_engineering_universe_from_mt5_probe
from finagent.domain.instruments import (
    InstrumentMappingEvidence,
    InstrumentMappingStatus,
)


def _utc() -> datetime:
    return datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _symbol(
    symbol: str,
    *,
    visible: bool = True,
    tradable: bool = True,
    path: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "finagent.mt5-symbol-spec.v1",
        "spec_id": f"mt5-symbol-{symbol.lower()}",
        "symbol": symbol,
        "path": path or f"Nasdaq\\Stock\\{symbol}",
        "visible": visible,
        "tradable": tradable,
        "trade_mode": 4 if tradable else 0,
        "trade_calc_mode": 32,
        "point": 0.01,
        "tick_size": 0.01,
        "tick_value": 0.01,
        "contract_size": 1.0,
        "volume_min": 1.0,
        "volume_max": 1_000_000.0,
        "volume_step": 1.0,
        "margin_initial": 0.0,
        "margin_maintenance": 0.0,
        "swap_mode": 0,
        "swap_long": 0.0,
        "swap_short": 0.0,
        "filling_mode": 1,
        "order_mode": 127,
        "currency_base": "USD",
        "currency_profit": "USD",
        "currency_margin": "USD",
    }


def _probe(*symbols: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": "finagent.mt5-capability-probe-report.v2",
        "probe_id": "mt5-capability-probe-real",
        "probed_at": "2026-09-01T09:07:56+00:00",
        "terminal": {
            "capability_id": "mt5-terminal-real",
            "broker_server": "MetaQuotes-Demo",
        },
        "symbols": list(symbols),
    }


def test_explicit_operator_attestation_can_build_engineering_universe() -> None:
    report = materialize_engineering_universe_from_mt5_probe(
        _probe(_symbol("MSFT")),
        mapping_pairs=(("MSFT", "MSFT"),),
        accepted_research_symbols=frozenset({"MSFT"}),
        generated_at=_utc(),
    )

    assert report.accepted is True
    assert report.blockers == ()
    assert report.universe is not None
    mapping = report.mappings[0]
    assert mapping.status is InstrumentMappingStatus.ACCEPTED_FOR_ENGINEERING
    assert mapping.evidence.symbol_text_matches is True
    assert mapping.evidence.broker_path_is_exchange_authority is False
    assert "identity:broker_path_not_exchange_authority" in report.limitations


def test_same_symbol_is_review_required_without_attestation() -> None:
    report = materialize_engineering_universe_from_mt5_probe(
        _probe(_symbol("MSFT")),
        mapping_pairs=(("MSFT", "MSFT"),),
        generated_at=_utc(),
    )

    assert report.accepted is False
    assert report.universe is None
    assert report.mappings[0].status is InstrumentMappingStatus.REVIEW_REQUIRED
    assert report.blockers == ("mapping:MSFT:operator_attestation_required",)


def test_explicit_suffix_mapping_does_not_require_ad_hoc_normalization() -> None:
    report = materialize_engineering_universe_from_mt5_probe(
        _probe(_symbol("MSFT.cfd")),
        mapping_pairs=(("MSFT", "MSFT.cfd"),),
        accepted_research_symbols=frozenset({"MSFT"}),
        generated_at=_utc(),
    )

    assert report.accepted is True
    assert report.mappings[0].broker.broker_symbol == "MSFT.cfd"
    assert report.mappings[0].evidence.symbol_text_matches is False


def test_missing_or_untradable_broker_symbol_fails_closed() -> None:
    missing = materialize_engineering_universe_from_mt5_probe(
        _probe(_symbol("MSFT")),
        mapping_pairs=(("NVDA", "NVDA"),),
        accepted_research_symbols=frozenset({"NVDA"}),
        generated_at=_utc(),
    )
    assert missing.accepted is False
    assert missing.blockers == ("mapping:NVDA:broker_symbol_missing:NVDA",)

    disabled = materialize_engineering_universe_from_mt5_probe(
        _probe(_symbol("MSFT", tradable=False)),
        mapping_pairs=(("MSFT", "MSFT"),),
        accepted_research_symbols=frozenset({"MSFT"}),
        generated_at=_utc(),
    )
    assert disabled.accepted is False
    assert disabled.mappings[0].status is InstrumentMappingStatus.REJECTED
    assert disabled.blockers == ("mapping:MSFT:broker_symbol_not_tradable",)


def test_mt5_path_cannot_be_promoted_to_exchange_authority() -> None:
    with pytest.raises(ValueError, match="cannot be promoted"):
        InstrumentMappingEvidence(
            research_instrument_id="research-1",
            broker_instrument_id="broker-1",
            mt5_probe_id="probe-1",
            observed_at=_utc(),
            research_symbol="MSFT",
            broker_symbol="MSFT",
            symbol_text_matches=True,
            quote_currency_matches=True,
            broker_path="Nasdaq\\Stock\\MSFT",
            operator_attested_same_security=True,
            broker_path_is_exchange_authority=True,
        )


def test_materialization_identity_is_deterministic_for_same_evidence() -> None:
    kwargs = {
        "mapping_pairs": (("MSFT", "MSFT"),),
        "accepted_research_symbols": frozenset({"MSFT"}),
        "generated_at": _utc(),
    }
    first = materialize_engineering_universe_from_mt5_probe(
        _probe(_symbol("MSFT")),
        **kwargs,
    )
    second = materialize_engineering_universe_from_mt5_probe(
        _probe(_symbol("MSFT")),
        **kwargs,
    )

    assert first.materialization_id == second.materialization_id
    assert first.universe is not None
    assert second.universe is not None
    assert first.universe.universe_id == second.universe.universe_id
