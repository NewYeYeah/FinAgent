from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
from typing import Any, Mapping

import pytest

from finagent.backtest.ashare_reserve import AshareReservePortfolioEngine
from finagent.research.ashare_reserve import SQLiteReserveEligibilityStore
from finagent.research.ashare_reserve_lifecycle import SQLiteReserveConsumptionStore
from finagent.research.ashare_reserve_runner import (
    FINAL_TRAINING_RULE_ID,
    RESERVE_EXECUTION_PROTOCOL_ID,
    TERMINAL_POLICY_RULE_ID,
    AshareReserveOneShotRunner,
    ReserveAccessState,
    ReservePortfolioEvaluation,
    ReserveTerminalStatus,
    SQLiteReserveTerminalEvidenceStore,
)

from tests.test_ashare_reserve_eligibility_a5 import _prepared, _seal


NOW = datetime(2026, 8, 29, 4, 0, tzinfo=UTC)


class StepClock:
    def __init__(self) -> None:
        self.values = [
            datetime(2026, 8, 29, 4, 0, tzinfo=UTC),
            datetime(2026, 8, 29, 4, 1, tzinfo=UTC),
            datetime(2026, 8, 29, 4, 2, tzinfo=UTC),
            datetime(2026, 8, 29, 4, 3, tzinfo=UTC),
        ]
        self.index = 0

    def __call__(self) -> datetime:
        value = self.values[min(self.index, len(self.values) - 1)]
        self.index += 1
        return value


class FakeEngine:
    def __init__(self, *, fail_policy: bool = False, error: Exception | None = None) -> None:
        self.fail_policy = fail_policy
        self.error = error
        self.preflight_calls = 0
        self.evaluate_calls = 0

    def preflight(self, *, seal, a26_report, a4_report) -> None:
        self.preflight_calls += 1
        assert a26_report["program_result_id"] == seal.program_result_id
        assert a4_report["portfolio_validation_id"] == seal.portfolio_validation_id

    def evaluate(self, *, seal, a26_report, a4_report) -> ReservePortfolioEvaluation:
        self.evaluate_calls += 1
        if self.error is not None:
            raise self.error
        failed = ("NET_SHARPE_BELOW_THRESHOLD",) if self.fail_policy else ()
        return ReservePortfolioEvaluation(
            engine_id="fake-a5-engine-v1",
            reserve_dataset_digest="reserve-dataset-digest",
            fold={
                "fold_id": "a5-reserve-reserve-v1",
                "train_range": ["2023-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"],
                "test_range": ["2025-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"],
            },
            aggregate={
                "net_metrics": {"total_return": 0.12, "sharpe": 1.1},
                "gross_metrics": {"total_return": 0.14, "sharpe": 1.2},
                "cash_fallback_ratio": 0.0,
            },
            policy={"min_net_sharpe": 0.0},
            failed_reason_codes=failed,
            ledger_rows=(
                {"session": "2025-01-02", "net_nav": 1.0},
                {"session": "2025-01-03", "net_nav": 1.01},
            ),
        )


def _runner(tmp_path: Path, engine: FakeEngine):
    a26, a4, *_ = _prepared(tmp_path)
    seal = _seal(tmp_path, code_git_sha="a5-runtime-sha")
    eligibility = SQLiteReserveEligibilityStore(tmp_path / "eligibility.sqlite")
    eligibility.register(seal)
    consumption = SQLiteReserveConsumptionStore(tmp_path / "consumption.sqlite")
    terminal = SQLiteReserveTerminalEvidenceStore(tmp_path / "terminal.sqlite")
    runner = AshareReserveOneShotRunner(
        eligibility_store=eligibility,
        consumption_store=consumption,
        terminal_store=terminal,
        engine=engine,
        clock=StepClock(),
    )
    return runner, terminal, seal, a26, a4


def test_a5p2_pass_is_terminal_and_does_not_auto_promote(tmp_path: Path) -> None:
    engine = FakeEngine()
    runner, terminal_store, seal, a26, a4 = _runner(tmp_path, engine)
    result = runner.run(
        seal=seal,
        a26_report=a26,
        a4_report=a4,
        runtime_code_git_sha="a5-runtime-sha",
        actor="human-operator",
    )
    terminal = result.terminal
    assert terminal.status is ReserveTerminalStatus.PASS
    assert terminal.to_dict()["promotion_eligible"] is False
    assert terminal.to_dict()["reserve_access_state"] == "ACCESSED"
    assert terminal.to_dict()["consumed_state_persistence"] == "DURABLE_PRE_ACCESS_V1"
    assert terminal.reserve_access_state is ReserveAccessState.ACCESSED
    claim = runner.consumption_store.get_claim_for_reserve(seal.reserve_id)
    assert claim.claim_id == terminal.consumption_claim_id
    assert "RESERVE_PASS_TERMINAL" in terminal.reason_codes
    assert result.ledger_bytes is not None
    assert terminal_store.get_for_reserve(seal.reserve_id).terminal_evidence_id == terminal.terminal_evidence_id
    assert engine.preflight_calls == 1
    assert engine.evaluate_calls == 1


def test_a5p2_fail_is_legal_terminal_result(tmp_path: Path) -> None:
    engine = FakeEngine(fail_policy=True)
    runner, _, seal, a26, a4 = _runner(tmp_path, engine)
    terminal = runner.run(
        seal=seal,
        a26_report=a26,
        a4_report=a4,
        runtime_code_git_sha="a5-runtime-sha",
        actor="human-operator",
    ).terminal
    assert terminal.status is ReserveTerminalStatus.FAIL
    assert "POLICY_NET_SHARPE_BELOW_THRESHOLD" in terminal.reason_codes
    assert "RESERVE_FAIL_TERMINAL" in terminal.reason_codes


def test_a5p2_terminal_schema_exposes_only_pass_or_fail(tmp_path: Path) -> None:
    assert {status.value for status in ReserveTerminalStatus} == {"RESERVE_PASS", "RESERVE_FAIL"}


def test_a5p2_terminal_payload_cannot_fake_a5p3_consumed_state(tmp_path: Path) -> None:
    engine = FakeEngine()
    runner, _, seal, a26, a4 = _runner(tmp_path, engine)
    terminal = runner.run(
        seal=seal,
        a26_report=a26,
        a4_report=a4,
        runtime_code_git_sha="a5-runtime-sha",
        actor="human-operator",
    ).terminal
    from dataclasses import replace as dc_replace
    from finagent.research.ashare_reserve_runner import ReserveTerminalEvidence

    legacy = dc_replace(
        terminal,
        consumption_claim_id="",
        consumed_at=None,
        reserve_access_state=ReserveAccessState.LEGACY_ACCESSED,
    )
    payload = legacy.to_dict()
    payload["consumed_state_persistence"] = "CONSUMED"
    with pytest.raises(ValueError, match="cannot claim durable consumed-state"):
        ReserveTerminalEvidence.from_dict(payload)


def test_a5p2_runtime_code_or_report_drift_fails_before_reserve_access(tmp_path: Path) -> None:
    engine = FakeEngine()
    runner, _, seal, a26, a4 = _runner(tmp_path, engine)
    with pytest.raises(PermissionError, match="runtime Git identity"):
        runner.run(
            seal=seal,
            a26_report=a26,
            a4_report=a4,
            runtime_code_git_sha="different-sha",
            actor="human-operator",
        )
    assert engine.preflight_calls == 0
    assert engine.evaluate_calls == 0
    with pytest.raises(KeyError):
        runner.consumption_store.get_claim_for_seal(seal.seal_id)

    changed = dict(a26)
    changed["program_status"] = "changed"
    with pytest.raises(ValueError, match="A2.6 report differs"):
        runner.run(
            seal=seal,
            a26_report=changed,
            a4_report=a4,
            runtime_code_git_sha="a5-runtime-sha",
            actor="human-operator",
        )
    assert engine.evaluate_calls == 0


def test_a5p2_existing_terminal_is_idempotent_without_reaccess(tmp_path: Path) -> None:
    engine = FakeEngine()
    runner, _, seal, a26, a4 = _runner(tmp_path, engine)
    first = runner.run(
        seal=seal,
        a26_report=a26,
        a4_report=a4,
        runtime_code_git_sha="a5-runtime-sha",
        actor="human-operator",
    )
    second = runner.run(
        seal=seal,
        a26_report=a26,
        a4_report=a4,
        runtime_code_git_sha="a5-runtime-sha",
        actor="second-operator",
    )
    assert second.terminal.terminal_evidence_id == first.terminal.terminal_evidence_id
    assert second.ledger_bytes == first.ledger_bytes
    assert engine.evaluate_calls == 1


def test_a5p2_operational_error_is_terminal_and_automatic_retry_is_blocked(tmp_path: Path) -> None:
    engine = FakeEngine(error=RuntimeError("synthetic reserve failure"))
    runner, _, seal, a26, a4 = _runner(tmp_path, engine)
    first = runner.run(
        seal=seal,
        a26_report=a26,
        a4_report=a4,
        runtime_code_git_sha="a5-runtime-sha",
        actor="human-operator",
    )
    assert first.terminal.status is ReserveTerminalStatus.FAIL
    assert first.terminal.error_type == "RuntimeError"
    assert "EXECUTION_FAILURE_AFTER_DURABLE_CONSUMPTION" in first.terminal.reason_codes
    assert "AUTOMATIC_RETRY_FORBIDDEN" in first.terminal.reason_codes
    second = runner.run(
        seal=seal,
        a26_report=a26,
        a4_report=a4,
        runtime_code_git_sha="a5-runtime-sha",
        actor="human-operator",
    )
    assert second.terminal.terminal_evidence_id == first.terminal.terminal_evidence_id
    assert engine.evaluate_calls == 1


def test_a5p2_reads_a5p1_seal_without_mutating_eligibility_identity(tmp_path: Path) -> None:
    seal = _seal(tmp_path, code_git_sha="a5-runtime-sha")
    assert "a5_execution_protocol" not in seal.protocol_snapshot
    assert seal.read_json(seal.write_json(tmp_path / "seal.json")).seal_id == seal.seal_id
    execution_id = AshareReserveOneShotRunner.execution_id(seal)
    assert RESERVE_EXECUTION_PROTOCOL_ID == "a5-one-shot-reserve-execution-v1"
    assert FINAL_TRAINING_RULE_ID == "all-pre-reserve-half-open-v1"
    assert TERMINAL_POLICY_RULE_ID == "reuse-frozen-a4-economic-policy-v1"
    assert execution_id.startswith("ashare-reserve-run-")


@dataclass
class FakeArtifact:
    digest: str


class FakePolicy:
    def to_dict(self) -> dict[str, float]:
        return {"min_net_sharpe": 0.0}


class FakeConfig:
    policy = FakePolicy()

    def __init__(self, payload: Mapping[str, object]) -> None:
        self.payload = dict(payload)

    def to_dict(self) -> dict[str, object]:
        return dict(self.payload)


class FakeFeeSchedule:
    def __init__(self, payload: Mapping[str, object], schedule_id: str) -> None:
        self.payload = dict(payload)
        self.schedule_id = schedule_id

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        if include_id:
            return {**self.payload, "schedule_id": self.schedule_id}
        return dict(self.payload)


class FakeProbeDataset:
    def __init__(self, *, version: str, digest: str) -> None:
        self.artifact = SimpleNamespace(version=version, digest=digest)
        self._split = SimpleNamespace(timestamps=(datetime(2025, 1, 2, tzinfo=UTC),))

    def get_split(self, name: str):
        assert name == "a5_reserve_probe"
        return self._split


class FakeInferenceAdapter:
    def __init__(self, *, version: str) -> None:
        self.version = version
        self.requests: list[Any] = []

    def build_dataset(self, request):
        self.requests.append(request)
        return FakeProbeDataset(version=self.version, digest="reserve-probe-digest")


def _plain_json(value):
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain_json(item) for item in value]
    return value


def _engine_ready_seal(seal):
    from finagent.services.ashare_execution import AshareFeeSchedule

    snapshot = _plain_json(seal.protocol_snapshot)
    program_spec = snapshot["a2p6_program_spec"]
    if not program_spec["walk_forward_plan"]["folds"]:
        program_spec["walk_forward_plan"]["folds"] = [
            {
                "fold_id": "fold-pre-reserve",
                "train": [
                    "2023-01-01T00:00:00+00:00",
                    "2024-01-01T00:00:00+00:00",
                ],
                "test": [
                    "2024-01-01T00:00:00+00:00",
                    "2025-01-01T00:00:00+00:00",
                ],
            }
        ]
    spec = snapshot["a4_validation_spec"]
    fee_schedule = AshareFeeSchedule()
    spec["net_execution_config"]["fee_schedule"] = fee_schedule.to_dict()
    spec["fee_schedule_id"] = fee_schedule.schedule_id
    protocol_digest = hashlib.sha256(
        json.dumps(
            snapshot,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return replace(seal, protocol_snapshot=snapshot, protocol_digest=protocol_digest)


class FakeValidator:
    def __init__(self, seal, inference_adapter: FakeInferenceAdapter) -> None:
        spec = seal.protocol_snapshot["a4_validation_spec"]
        self.artifacts = (FakeArtifact(seal.selected_feature_digests[0]),)
        self.weights = seal.selected_weights
        self.directions = seal.selected_directions
        self.config = FakeConfig(spec["validation_config"])  # type: ignore[index]
        net = spec["net_execution_config"]  # type: ignore[index]
        fees = net["fee_schedule"]  # type: ignore[index]
        fee_payload = {key: value for key, value in fees.items() if key != "schedule_id"}  # type: ignore[union-attr]
        self.net_session = SimpleNamespace(
            compiler=SimpleNamespace(
                config=SimpleNamespace(
                    slippage_bps=float(net["slippage_bps"]),  # type: ignore[index]
                    require_price_limits=bool(net["require_price_limits"]),  # type: ignore[index]
                ),
                fee_schedule=FakeFeeSchedule(fee_payload, str(spec["fee_schedule_id"])),  # type: ignore[index]
            )
        )
        zero_fee_payload = {
            "broker_commission_rate": 0.0,
            "minimum_broker_commission": 0.0,
            "stamp_duty_sell_rate": 0.0,
            "transfer_fee_rate": 0.0,
            "sse_szse_handling_rate": 0.0,
            "bse_handling_rate": 0.0,
            "regulatory_fee_rate": 0.0,
            "pass_through_exchange_handling": False,
            "pass_through_regulatory_fee": False,
        }
        self.gross_session = SimpleNamespace(
            compiler=SimpleNamespace(
                config=SimpleNamespace(slippage_bps=0.0),
                fee_schedule=FakeFeeSchedule(zero_fee_payload, "zero-fee"),
            )
        )
        self.inference_adapter = inference_adapter
        self.fold = None
        self.test_sessions = None

    def run_terminal_fold(self, *, fold, universe, primary_label, test_sessions=None):
        self.fold = fold
        self.test_sessions = test_sessions
        fold_result = SimpleNamespace(to_dict=lambda: {
            "fold_id": fold.fold_id,
            "train_range": [fold.train.start.isoformat(), fold.train.end.isoformat()],
            "test_range": [fold.test.start.isoformat(), fold.test.end.isoformat()],
        })
        aggregate = SimpleNamespace(to_dict=lambda: {
            "net_metrics": {"total_return": 0.05, "sharpe": 0.8},
            "gross_metrics": {"total_return": 0.06, "sharpe": 0.9},
        })
        return fold_result, aggregate, (), ({"point": {"net_nav": 1.05}},)


def test_concrete_a5_engine_uses_all_pre_reserve_training_and_exact_reserve_test(tmp_path: Path) -> None:
    a26, a4, *_ = _prepared(tmp_path)
    seal = _engine_ready_seal(_seal(tmp_path, code_git_sha="a5-runtime-sha"))
    inference = FakeInferenceAdapter(version=seal.data_version)
    validator = FakeValidator(seal, inference)
    # AssetId construction is irrelevant to this fake validator; use the real class contract.
    from finagent.domain.assets import AssetId, AssetType

    asset = AssetId("600000.SH", AssetType.EQUITY, "SSE", "CNY")
    engine = AshareReservePortfolioEngine(validator=validator, universe=(asset,))  # type: ignore[arg-type]
    engine.preflight(seal=seal, a26_report=a26, a4_report=a4)
    result = engine.evaluate(seal=seal, a26_report=a26, a4_report=a4)
    assert result.reserve_dataset_digest == "reserve-probe-digest"
    assert len(inference.requests) == 1
    assert validator.test_sessions == (datetime(2025, 1, 2, tzinfo=UTC).date(),)
    assert validator.fold.train.end.isoformat() == seal.reserve_start
    assert validator.fold.test.start.isoformat() == seal.reserve_start
    assert validator.fold.test.end.isoformat() == seal.reserve_end
    first_fold = seal.protocol_snapshot["a2p6_program_spec"]["walk_forward_plan"]["folds"][0]  # type: ignore[index]
    assert validator.fold.train.start.isoformat() == first_fold["train"][0]  # type: ignore[index]


def test_concrete_a5_engine_rejects_materialized_data_version_drift(tmp_path: Path) -> None:
    a26, a4, *_ = _prepared(tmp_path)
    seal = _engine_ready_seal(_seal(tmp_path, code_git_sha="a5-runtime-sha"))
    inference = FakeInferenceAdapter(version="different-data-version")
    validator = FakeValidator(seal, inference)
    from finagent.domain.assets import AssetId, AssetType

    asset = AssetId("600000.SH", AssetType.EQUITY, "SSE", "CNY")
    engine = AshareReservePortfolioEngine(validator=validator, universe=(asset,))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="dataset version differs"):
        engine.evaluate(seal=seal, a26_report=a26, a4_report=a4)
