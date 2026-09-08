from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from finagent.visualization.research_workspace import ResearchWorkspaceProjection


def _insert_run(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    call_id: str,
    result: dict[str, object],
) -> None:
    payload = {
        "task": {"objective": "Duplicate attempt fixture"},
        "context": {
            "started_at": "2026-09-08T06:00:00+00:00",
            "metadata": {
                "controller": "r4",
                "project_id": "r4-research",
                "thread_id": "thread-" + run_id,
            },
        },
    }
    connection.execute(
        "INSERT INTO agent_runs VALUES (?, ?, NULL)",
        (run_id, json.dumps(payload)),
    )
    connection.execute(
        "INSERT INTO agent_tool_calls VALUES (?, 1, ?, ?, ?)",
        (
            run_id,
            call_id,
            json.dumps(
                {
                    "tool_name": "evaluate_portfolio",
                    "arguments": {
                        "factor_set_id": "set-a",
                        "allocator_proposal_id": "alloc-a",
                        "hypothesis_id": "hyp-a",
                    },
                }
            ),
            json.dumps(
                {
                    "status": "succeeded",
                    "error": "",
                    "output": {
                        "research_result": result,
                        "research_state": {"resources": {}},
                    },
                }
            ),
        ),
    )


def test_duplicate_attempt_retains_attempt_identity_and_persisted_order(tmp_path: Path) -> None:
    database = tmp_path / "attempts.sqlite"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE agent_runs (
            run_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, decision_json TEXT
        );
        CREATE TABLE agent_tool_calls (
            run_id TEXT NOT NULL, sequence INTEGER NOT NULL, call_id TEXT NOT NULL,
            request_json TEXT NOT NULL, result_json TEXT
        );
        """
    )
    _insert_run(
        connection,
        run_id="z-original-run",
        call_id="z-original-call",
        result={
            "outcome": "PORTFOLIO_EVALUATED",
            "experiment_id": "exp-shared",
            "factor_ids": ["factor-a", "factor-b"],
            "preferred_allocator": "equal_weight",
            "summary": {
                "arms": {"equal_weight": {"mean_fold_return_5bp": 0.01}}
            },
        },
    )
    _insert_run(
        connection,
        run_id="a-duplicate-run",
        call_id="a-duplicate-call",
        result={
            "outcome": "DUPLICATE_EXPERIMENT",
            "experiment_id": "exp-shared",
            "original_request_id": "z-original-call",
            "original_outcome": "COMMITTED",
        },
    )
    connection.commit()
    connection.close()

    detail = ResearchWorkspaceProjection(database, cycle_paths=()).experiment("exp-shared")
    assert detail["attempt_count"] == 2
    assert detail["selection_semantics"] == (
        "persisted_agent_audit_run_ordinal_then_tool_sequence"
    )
    assert [item["status"] for item in detail["attempts"]] == ["completed", "duplicate"]
    assert [item["run_id"] for item in detail["attempts"]] == [
        "z-original-run",
        "a-duplicate-run",
    ]
    assert detail["item"]["status"] == "duplicate"
    assert detail["item"]["attempt_id"] == "a-duplicate-call"
    assert detail["attempts"][0]["authoritative_metrics"] == {
        "mean_fold_return_5bp": 0.01
    }
    assert detail["item"]["authoritative_metrics"] is None
    assert detail["item"]["browser_recomputation"] is False
