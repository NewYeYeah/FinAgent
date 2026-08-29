from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Mapping, Sequence

from finagent.domain.assets import AssetId
from finagent.domain.research import DatasetRequest, TimeRange
from finagent.research.ashare_reserve import ReserveEligibilitySeal
from finagent.research.ashare_reserve_runner import (
    FINAL_TRAINING_RULE_ID,
    RESERVE_EXECUTION_PROTOCOL_ID,
    TERMINAL_POLICY_RULE_ID,
    ReservePortfolioEvaluation,
)
from finagent.research.ashare_robust_program import AshareWalkForwardFold

from .ashare_portfolio import AshareExecutionAwarePortfolioValidator


class AshareReservePortfolioEngine:
    """Run the frozen A4 mechanics once on the sealed A5 reserve interval."""

    ENGINE_ID = "ashare-a5-reserve-portfolio-engine-v1"

    def __init__(
        self,
        *,
        validator: AshareExecutionAwarePortfolioValidator,
        universe: tuple[AssetId, ...],
    ) -> None:
        if not universe or len(set(universe)) != len(universe):
            raise ValueError("A5 reserve universe must be non-empty and unique")
        self.validator = validator
        self.universe = universe

    @staticmethod
    def _mapping(value: object, name: str) -> Mapping[str, Any]:
        if not isinstance(value, Mapping):
            raise TypeError(f"{name} must be a JSON object")
        return value

    @staticmethod
    def _sequence(value: object, name: str) -> Sequence[object]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
            raise TypeError(f"{name} must be a JSON array")
        return value

    @staticmethod
    def _plain_json(value: object) -> object:
        if isinstance(value, Mapping):
            return {str(key): AshareReservePortfolioEngine._plain_json(item) for key, item in value.items()}
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [AshareReservePortfolioEngine._plain_json(item) for item in value]
        return value

    @staticmethod
    def _canonical(value: object) -> str:
        return json.dumps(
            AshareReservePortfolioEngine._plain_json(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def _protocol(self, seal: ReserveEligibilitySeal) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        snapshot = self._mapping(seal.protocol_snapshot, "protocol_snapshot")
        program_spec = self._mapping(snapshot.get("a2p6_program_spec"), "a2p6_program_spec")
        a4_spec = self._mapping(snapshot.get("a4_validation_spec"), "a4_validation_spec")
        return program_spec, a4_spec

    def preflight(
        self,
        *,
        seal: ReserveEligibilitySeal,
        a26_report: Mapping[str, Any],
        a4_report: Mapping[str, Any],
    ) -> None:
        program_spec, a4_spec = self._protocol(seal)
        if str(a26_report.get("program_result_id")) != seal.program_result_id:
            raise ValueError("A5 engine A2.6 identity differs from eligibility seal")
        if str(a4_report.get("portfolio_validation_id")) != seal.portfolio_validation_id:
            raise ValueError("A5 engine A4 identity differs from eligibility seal")
        if str(program_spec.get("data_version")) != seal.data_version:
            raise ValueError("A5 engine data version differs from eligibility seal")
        if str(program_spec.get("primary_label", "")).strip() == "":
            raise ValueError("A5 frozen program has no primary label")

        artifact_digests = tuple(artifact.digest for artifact in self.validator.artifacts)
        if artifact_digests != seal.selected_feature_digests:
            raise ValueError("A5 validator factor artifacts differ from eligibility seal")
        if tuple(self.validator.weights) != seal.selected_weights:
            raise ValueError("A5 validator factor weights differ from eligibility seal")
        if tuple(self.validator.directions) != seal.selected_directions:
            raise ValueError("A5 validator factor directions differ from eligibility seal")
        if self._canonical(self.validator.config.to_dict()) != self._canonical(
            self._mapping(a4_spec.get("validation_config"), "validation_config")
        ):
            raise ValueError("A5 validator numeric/economic policy differs from frozen A4")

        net = self._mapping(a4_spec.get("net_execution_config"), "net_execution_config")
        compiler = self.validator.net_session.compiler
        if float(net.get("slippage_bps", -1.0)) != compiler.config.slippage_bps:
            raise ValueError("A5 net slippage differs from frozen A4")
        if bool(net.get("require_price_limits")) != compiler.config.require_price_limits:
            raise ValueError("A5 price-limit policy differs from frozen A4")
        frozen_fees = self._mapping(net.get("fee_schedule"), "fee_schedule")
        if self._canonical(compiler.fee_schedule.to_dict()) != self._canonical(frozen_fees):
            raise ValueError("A5 fee schedule differs from frozen A4")
        if compiler.fee_schedule.schedule_id != str(a4_spec.get("fee_schedule_id")):
            raise ValueError("A5 fee schedule identity differs from frozen A4")

        gross = self.validator.gross_session.compiler
        if gross.config.slippage_bps != 0.0:
            raise ValueError("A5 gross comparator must retain zero slippage")
        gross_fees = gross.fee_schedule.to_dict(include_id=False)
        if any(float(value) != 0.0 for key, value in gross_fees.items() if not key.startswith("pass_")):
            raise ValueError("A5 gross comparator must retain zero fees")
        if any(bool(value) for key, value in gross_fees.items() if key.startswith("pass_")):
            raise ValueError("A5 gross comparator cannot enable pass-through fees")

    def _ranges(self, seal: ReserveEligibilitySeal) -> tuple[TimeRange, TimeRange, str]:
        program_spec, _ = self._protocol(seal)
        plan = self._mapping(program_spec.get("walk_forward_plan"), "walk_forward_plan")
        folds = self._sequence(plan.get("folds"), "walk_forward folds")
        if not folds:
            raise ValueError("A5 final-training rule requires at least one A2.6 fold")
        first = self._mapping(folds[0], "first walk-forward fold")
        train_values = self._sequence(first.get("train"), "first fold train")
        if len(train_values) != 2:
            raise ValueError("first A2.6 train range must contain [start, end]")
        train_start = datetime.fromisoformat(str(train_values[0]))
        reserve_start = datetime.fromisoformat(seal.reserve_start)
        reserve_end = datetime.fromisoformat(seal.reserve_end)
        primary_label = str(program_spec.get("primary_label", "")).strip()
        return (
            TimeRange(train_start, reserve_start),
            TimeRange(reserve_start, reserve_end),
            primary_label,
        )

    def evaluate(
        self,
        *,
        seal: ReserveEligibilitySeal,
        a26_report: Mapping[str, Any],
        a4_report: Mapping[str, Any],
    ) -> ReservePortfolioEvaluation:
        # Re-run the zero-access checks immediately before the first reserve read. This
        # avoids a mutable caller swapping the validator configuration between phases.
        self.preflight(seal=seal, a26_report=a26_report, a4_report=a4_report)
        train_range, reserve_range, primary_label = self._ranges(seal)

        # This is the first deliberate reserve observation access in A5-2. The probe
        # binds the actual materialized reserve dataset to the preregistered data version.
        probe = self.validator.inference_adapter.build_dataset(
            DatasetRequest(
                universe=self.universe,
                features=("close",),
                labels=(primary_label,),
                splits={"a5_reserve_probe": reserve_range},
                dataset_id=f"a5-{seal.reserve_id}-reserve-probe",
                metadata={
                    "scope": "A5 one-shot reserve access; terminal use only",
                    "seal_id": seal.seal_id,
                    "execution_protocol_id": RESERVE_EXECUTION_PROTOCOL_ID,
                },
            )
        )
        if probe.artifact.version != seal.data_version:
            raise ValueError("materialized A5 reserve dataset version differs from eligibility seal")
        probe_split = probe.get_split("a5_reserve_probe")
        reserve_sessions = tuple(
            timestamp.astimezone(UTC).date() for timestamp in probe_split.timestamps
        )
        if not reserve_sessions:
            raise ValueError("A5 reserve interval contains no materialized sessions")
        if tuple(sorted(set(reserve_sessions))) != reserve_sessions:
            raise ValueError("A5 reserve materialization sessions must be unique and ordered")

        fold = AshareWalkForwardFold(
            fold_id=f"a5-reserve-{seal.reserve_id}",
            train_split="a5_final_train",
            test_split="a5_reserve",
            train=train_range,
            test=reserve_range,
        )
        fold_result, aggregate, failed_reasons, rows = self.validator.run_terminal_fold(
            fold=fold,
            universe=self.universe,
            primary_label=primary_label,
            test_sessions=reserve_sessions,
        )
        return ReservePortfolioEvaluation(
            engine_id=self.ENGINE_ID,
            reserve_dataset_digest=probe.artifact.digest,
            fold=fold_result.to_dict(),
            aggregate=aggregate.to_dict(),
            policy=self.validator.config.policy.to_dict(),
            failed_reason_codes=failed_reasons,
            ledger_rows=rows,
        )
