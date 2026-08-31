from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from finagent.application import (
    ApplicationCommandExecution,
    ApplicationCommandInvocation,
    ReviewBundleExportApplicationService,
    SQLiteCommandStore,
)
from finagent.backtest import (
    canonical_execution_ledger_digest,
    materialize_strategy_decision_rows,
    write_strategy_decision_series,
)
from finagent.runtime.ashare_historical_acceptance import (
    AshareHistoricalAcceptanceArtifacts,
    verify_ashare_historical_acceptance,
)
from tests.test_market_bar_series_ac2 import _write_ac2
from tests.test_portfolio_execution_v44 import _write_v44
from tests.test_strategy_decision_series_v40 import _alpha

pytest_plugins = ("tests.test_factor_series_v41",)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _ledger_rows(path: Path) -> tuple[dict[str, object], ...]:
    output: list[dict[str, object]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        value = json.loads(raw)
        assert isinstance(value, dict)
        output.append(value)
    return tuple(output)


def _bind_v44_to_robust(root: Path, robust: dict[str, object]) -> tuple[str, str]:
    validation_id, _ = _write_v44(root)
    a4_path = root / "a4.json"
    ledger_path = root / "a4.jsonl"
    manifest_path = root / "a4.strategy-decisions.json"
    data_path = root / "a4.strategy-decisions.parquet"

    a4 = json.loads(a4_path.read_text(encoding="utf-8"))
    assert isinstance(a4, dict)
    spec = a4["validation_spec"]
    assert isinstance(spec, dict)
    program = robust["program_spec"]
    selection = robust["frozen_selection"]
    assert isinstance(program, dict)
    assert isinstance(selection, dict)
    components = selection["components"]
    assert isinstance(components, list) and components

    spec["source_program_result_id"] = robust["program_result_id"]
    spec["source_program_spec_id"] = program["spec_id"]
    spec["source_selection_id"] = selection["selection_id"]
    spec["data_version"] = robust["data_version"]
    spec["source_report_digest"] = hashlib.sha256(
        _canonical_json(robust).encode("utf-8")
    ).hexdigest()
    spec["selected_feature_digests"] = [item["feature_digest"] for item in components]
    spec["selected_weights"] = [item["weight"] for item in components]
    spec["selected_directions"] = [item["direction"] for item in components]
    a4_path.write_text(json.dumps(a4, sort_keys=True), encoding="utf-8")
    (root / "a26.json").unlink(missing_ok=True)

    ledger = _ledger_rows(ledger_path)
    assert canonical_execution_ledger_digest(ledger) == a4["ledger_digest"]
    rows = materialize_strategy_decision_rows(
        ledger_rows=ledger,
        expected_ledger_digest=str(a4["ledger_digest"]),
        initial_cash=1000.0,
        alpha_provider=_alpha,
    )
    manifest = write_strategy_decision_series(
        a4_report=a4,
        rows=rows,
        source_report_path=a4_path,
        source_ledger_path=ledger_path,
        manifest_path=manifest_path,
        data_path=data_path,
    )
    assert manifest.portfolio_validation_id == validation_id
    return validation_id, manifest.series_id


def _record_success(
    store: SQLiteCommandStore,
    *,
    command_id: str,
    evidence_ids: tuple[str, ...] = (),
    artifact_paths: tuple[str, ...] = (),
    outputs: dict[str, object] | None = None,
) -> None:
    record, created = store.create(
        request_key=f"ac3-ci:{command_id}",
        command_id=command_id,
        config_snapshot_id=(
            None if command_id == "review.export_bundle" else f"snapshot:{command_id}"
        ),
        context={},
        parameters={},
        requested_by="ac3-ci",
        accepted=True,
    )
    assert created
    store.mark_running(record.run.command_run_id)
    store.mark_succeeded(
        record.run.command_run_id,
        ApplicationCommandExecution(
            command_id=command_id,
            status="succeeded",
            outputs=outputs or {},
            artifact_paths=artifact_paths,
            evidence_ids=evidence_ids,
            message="A-C3 CI contract fixture",
        ),
    )


def test_ac3_ci_contract_fixture_validates_full_chain_but_cannot_close_real_acceptance(
    v41_evidence: dict[str, object],
) -> None:
    root = Path(v41_evidence["root"])
    robust_path = Path(v41_evidence["report"])
    factor_manifest = Path(v41_evidence["manifest"])
    robust = json.loads(robust_path.read_text(encoding="utf-8"))
    assert isinstance(robust, dict)
    data_version = str(robust["data_version"])

    validation_id, strategy_series_id = _bind_v44_to_robust(root, robust)
    strategy_manifest = root / "a4.strategy-decisions.json"
    market_series_id = _write_ac2(
        root,
        strategy_series_id,
        validation_id,
        data_version=data_version,
    )
    market_manifest = root / "market-bars.json"
    assert market_series_id

    certification = root / "certification.json"
    certification.write_text(
        json.dumps(
            {
                "schema_version": "finagent.local-ashare-certification.v1",
                "passed": True,
                "data_version": "ci-fast-certification",
            }
        ),
        encoding="utf-8",
    )
    development_acceptance_id = "development-ac3-ci"
    development = root / "development.json"
    development.write_text(
        json.dumps(
            {
                "schema_version": "finagent.ashare-factor-research-acceptance.v2",
                "acceptance_id": development_acceptance_id,
                "passed": True,
                "system_acceptance": {"passed": True, "status": "PASS"},
                "data_version": data_version,
                "reserve": {
                    "start": "2023-01-01T00:00:00+00:00",
                    "end": "2024-01-01T00:00:00+00:00",
                    "status": "untouched",
                },
            }
        ),
        encoding="utf-8",
    )

    command_store = root / "commands.sqlite"
    store = SQLiteCommandStore(command_store)
    _record_success(
        store,
        command_id="data.certify_local_ashare",
        artifact_paths=(str(certification),),
        outputs={"passed": True, "output_path": str(certification)},
    )
    _record_success(
        store,
        command_id="research.run_development",
        evidence_ids=(development_acceptance_id,),
        artifact_paths=(str(development),),
        outputs={
            "evidence_id": development_acceptance_id,
            "report_path": str(development),
        },
    )
    _record_success(
        store,
        command_id="research.run_a2p6",
        evidence_ids=(str(robust["program_result_id"]),),
        artifact_paths=(str(robust_path),),
        outputs={
            "evidence_id": str(robust["program_result_id"]),
            "report_path": str(robust_path),
        },
    )
    _record_success(
        store,
        command_id="portfolio.run_a4",
        evidence_ids=(validation_id,),
        artifact_paths=(str(root / "a4.json"), str(root / "a4.jsonl")),
        outputs={
            "evidence_id": validation_id,
            "report_path": str(root / "a4.json"),
        },
    )

    review_bundle = root / f"finagent-review-{validation_id}.zip"
    review_execution = ReviewBundleExportApplicationService().execute(
        ApplicationCommandInvocation(
            command_id="review.export_bundle",
            parameters={
                "validation_id": validation_id,
                "reports": (str(root),),
                "output": str(review_bundle),
                "git_sha": "ac3-ci",
            },
            requested_by="ac3-ci",
        )
    )
    assert review_execution.status == "succeeded"
    review_record, created = store.create(
        request_key="ac3-ci:review.export_bundle",
        command_id="review.export_bundle",
        config_snapshot_id=None,
        context={"portfolio_validation_id": validation_id},
        parameters={"validation_id": validation_id},
        requested_by="ac3-ci",
        accepted=True,
    )
    assert created
    store.mark_running(review_record.run.command_run_id)
    store.mark_succeeded(review_record.run.command_run_id, review_execution)

    result = verify_ashare_historical_acceptance(
        artifacts=AshareHistoricalAcceptanceArtifacts(
            certification_report=certification,
            development_report=development,
            robust_report=robust_path,
            a4_report=root / "a4.json",
            a4_ledger=root / "a4.jsonl",
            factor_manifest=factor_manifest,
            strategy_manifest=strategy_manifest,
            market_bar_manifest=market_manifest,
            review_bundle=review_bundle,
            command_store=command_store,
            evidence_roots=(root,),
        ),
        mode="ci_contract_fixture",
        git_sha="ac3-ci",
        report_path=root / "ac3-acceptance.json",
    )

    assert result.contract_valid is True
    assert result.accepted is False
    assert result.payload["real_dataset_attested"] is False
    checks = result.payload["checks"]
    assert isinstance(checks, dict)
    assert all(checks.values())
    identities = result.payload["identities"]
    assert isinstance(identities, dict)
    assert identities["development_acceptance_id"] == development_acceptance_id
    assert identities["portfolio_validation_id"] == validation_id
    assert identities["strategy_series_id"] == strategy_series_id
    assert result.report_path.is_file()


def test_ac3_ci_acceptance_artifact_cannot_claim_real_data(
    v41_evidence: dict[str, object],
) -> None:
    root = Path(v41_evidence["root"])
    acceptance_path = root / "ac3-acceptance.json"
    assert acceptance_path.is_file()
    payload = json.loads(acceptance_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "ci_contract_fixture"
    assert payload["contract_valid"] is True
    assert payload["accepted"] is False
    assert payload["real_dataset_attested"] is False
    assert "verify_content=true" in payload["acceptance_semantics"]
