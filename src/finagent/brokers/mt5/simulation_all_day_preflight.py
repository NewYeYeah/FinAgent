from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from finagent.brokers.mt5.continuous_quote_smoke import MT5ContinuousQuoteSmokeReport


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


@dataclass(frozen=True, slots=True)
class MT5SimulationAllDayPreflightPolicy:
    expected_broker_server: str = "MetaQuotes-Demo"
    required_symbols: tuple[str, ...] = ("EURUSD", "GBPUSD", "USDJPY")
    minimum_passed_symbol_count: int = 3
    schema_version: str = "finagent.mt5-simulation-all-day-preflight-policy.v1"

    def __post_init__(self) -> None:
        server = self.expected_broker_server.strip()
        symbols = tuple(dict.fromkeys(item.strip() for item in self.required_symbols if item.strip()))
        if not server:
            raise ValueError("expected_broker_server must be non-empty")
        if not symbols or symbols != self.required_symbols:
            raise ValueError("required_symbols must be non-empty, unique and normalized")
        if self.minimum_passed_symbol_count < 1:
            raise ValueError("minimum_passed_symbol_count must be >= 1")
        if self.minimum_passed_symbol_count > len(symbols):
            raise ValueError("minimum_passed_symbol_count cannot exceed required symbol count")
        object.__setattr__(self, "expected_broker_server", server)

    @property
    def policy_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="mt5-simulation-all-day-preflight-policy",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "expected_broker_server": self.expected_broker_server,
            "required_symbols": list(self.required_symbols),
            "minimum_passed_symbol_count": self.minimum_passed_symbol_count,
            "product_scope": "continuous_or_near_continuous_engineering_fixture",
            "us_research_universe_authority": False,
            "stage_exit_authority": False,
            "execution_authority": False,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


CANONICAL_MT5_SIMULATION_ALL_DAY_PREFLIGHT_POLICY = MT5SimulationAllDayPreflightPolicy()


@dataclass(frozen=True, slots=True)
class MT5SimulationAllDayPreflightReport:
    policy: MT5SimulationAllDayPreflightPolicy
    continuous_smoke: MT5ContinuousQuoteSmokeReport
    schema_version: str = "finagent.mt5-simulation-all-day-preflight-report.v1"

    @property
    def passed_symbols(self) -> tuple[str, ...]:
        required = set(self.policy.required_symbols)
        return tuple(
            check.symbol
            for check in self.continuous_smoke.checks
            if check.symbol in required and check.passed
        )

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.continuous_smoke.broker_server != self.policy.expected_broker_server:
            blockers.append("simulation_all_day:broker_server_mismatch")
        if tuple(self.continuous_smoke.requested_symbols) != self.policy.required_symbols:
            blockers.append("simulation_all_day:required_symbol_set_mismatch")
        if not self.continuous_smoke.clock_evidence.passed:
            blockers.append("simulation_all_day:broker_clock_evidence_failed")
        if not self.continuous_smoke.passed:
            blockers.append("simulation_all_day:continuous_smoke_failed")
        if len(self.passed_symbols) < self.policy.minimum_passed_symbol_count:
            blockers.append(
                "simulation_all_day:insufficient_passed_symbols:"
                f"{len(self.passed_symbols)}<{self.policy.minimum_passed_symbol_count}"
            )
        return tuple(dict.fromkeys(blockers))

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def report_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "policy_id": self.policy.policy_id,
                "continuous_smoke_report_id": self.continuous_smoke.report_id,
                "passed_symbols": list(self.passed_symbols),
            },
            prefix="mt5-simulation-all-day-preflight",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "policy": self.policy.to_dict(),
            "continuous_smoke_report_id": self.continuous_smoke.report_id,
            "continuous_smoke": self.continuous_smoke.to_dict(),
            "passed": self.passed,
            "blockers": list(self.blockers),
            "passed_symbols": list(self.passed_symbols),
            "product_scope": "continuous_or_near_continuous_engineering_fixture",
            "engineering_fixture_authority": self.passed,
            "us_research_universe_authority": False,
            "us_d3_certification_authority": False,
            "live_market_data_authority": False,
            "live_executable_spread_authority": False,
            "execution_authority": False,
            "order_authority": False,
            "live_capital_authority": False,
            "status_authority": False,
            "stage_exit_authority": False,
        }


def build_mt5_simulation_all_day_preflight_report(
    continuous_smoke: MT5ContinuousQuoteSmokeReport,
    *,
    policy: MT5SimulationAllDayPreflightPolicy = CANONICAL_MT5_SIMULATION_ALL_DAY_PREFLIGHT_POLICY,
) -> MT5SimulationAllDayPreflightReport:
    return MT5SimulationAllDayPreflightReport(
        policy=policy,
        continuous_smoke=continuous_smoke,
    )
