from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Market -> Factor deep link carries the explicit canonical factor identity before navigation.
path = ROOT / "workspace/src/workbench/market.tsx"
text = path.read_text(encoding="utf-8")
text = text.replace(
    'to={`/factors${search}`} onClick={() => select({ factor_id: factor.factor_id }, "factor_selected")}',
    'to={`/factors?factor=${encodeURIComponent(factor.factor_id)}${search ? `&${search.slice(1)}` : ""}`} onClick={() => select({ factor_id: factor.factor_id }, "factor_selected")}',
)
path.write_text(text, encoding="utf-8")

# Accepted-cycle product display is fail-closed everywhere.
path = ROOT / "workspace/src/workbench/experiments.tsx"
text = path.read_text(encoding="utf-8")
text = text.replace(
    'const accepted = cyclesQuery.data?.items.find((cycle) => cycle.terminal === "NO_ADAPTIVE_CANDIDATE") ?? cyclesQuery.data?.items[0];',
    'const accepted = cyclesQuery.data?.items.find((cycle) => cycle.accepted === true && cycle.terminal === "NO_ADAPTIVE_CANDIDATE");',
)
path.write_text(text, encoding="utf-8")

path = ROOT / "workspace/src/workbench/experimentsGraph.test.tsx"
text = path.read_text(encoding="utf-8")
text = text.replace(
    'items: [{ cycle_id: "cycle-a", protocol_id:',
    'items: [{ cycle_id: "cycle-a", accepted: true, review_status: "accepted", protocol_id:',
)
path.write_text(text, encoding="utf-8")

# Status count means explicitly accepted cycle count, not schema-matching attestation count.
path = ROOT / "src/finagent/visualization/research_workspace.py"
text = path.read_text(encoding="utf-8")
text = text.replace(
    '            "accepted_cycle_count": len(cycles["items"]),',
    '            "accepted_cycle_count": sum(item.get("accepted") is True for item in cycles["items"]),',
)
path.write_text(text, encoding="utf-8")

# Existing panel contract records the new canonical linked identities.
path = ROOT / "workspace/src/workbench/panels.test.ts"
text = path.read_text(encoding="utf-8")
text = text.replace(
    '      context_keys: ["program_id", "factor_id", "date_range", "fold_id"],',
    '      context_keys: ["program_id", "factor_id", "market_state_model_id", "experiment_id", "date_range", "fold_id"],',
)
text = text.replace(
    '    expect(defaultPanelRegistry.get("portfolio")).toMatchObject({',
    '    expect(defaultPanelRegistry.get("market")).toMatchObject({\n      status: "available",\n      route: "/market",\n      slot: "chart",\n      context_keys: ["market_state_model_id", "factor_id", "experiment_id", "run_id"],\n    });\n    expect(defaultPanelRegistry.get("portfolio")).toMatchObject({',
)
path.write_text(text, encoding="utf-8")

# WorkbenchContext regression for MarketState deep-link recovery.
path = ROOT / "workspace/src/workbench/context.test.ts"
text = path.read_text(encoding="utf-8")
text = text.replace(
    '      factor_id: "factor-a",\n      portfolio_validation_id:',
    '      factor_id: "factor-a",\n      market_state_model_id: "market-model-a",\n      portfolio_validation_id:',
    1,
)
text = text.replace(
    '    expect(serialized.get("factor")).toBe("factor-a");\n',
    '    expect(serialized.get("factor")).toBe("factor-a");\n    expect(serialized.get("market_model")).toBe("market-model-a");\n',
    1,
)
text = text.replace(
    '      factor_id: "factor-a",\n      portfolio_validation_id: "a4-validation-a",',
    '      factor_id: "factor-a",\n      market_state_model_id: "market-model-a",\n      portfolio_validation_id: "a4-validation-a",',
    1,
)
path.write_text(text, encoding="utf-8")

# Explicit duplicate/repaired attempt-order regression. Canonical experiment selection
# follows persisted audit run ordinal + tool sequence, never lexical run/call identity.
path = ROOT / "tests/test_market_factor_intelligence_v3.py"
text = path.read_text(encoding="utf-8")
text += r'''


def test_experiment_attempt_order_is_persisted_not_lexical_and_repair_is_explicit(
    tmp_path: Path,
) -> None:
    database = tmp_path / "attempts.sqlite"
    connection = sqlite3.connect(database)
    connection.executescript("""
        CREATE TABLE agent_runs (
            run_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, decision_json TEXT
        );
        CREATE TABLE agent_tool_calls (
            run_id TEXT NOT NULL, sequence INTEGER NOT NULL, call_id TEXT NOT NULL,
            request_json TEXT NOT NULL, result_json TEXT
        );
    """)

    def add(run_id: str, started_at: str, call_id: str, repaired: str | None) -> None:
        payload = {
            "task": {"objective": "Attempt-order fixture"},
            "context": {
                "started_at": started_at,
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
        result = {
            "outcome": "PORTFOLIO_EVALUATED",
            "experiment_id": "exp-shared",
            "factor_ids": ["factor-a", "factor-b"],
            "preferred_allocator": "equal_weight",
            "summary": {"arms": {"equal_weight": {"mean_fold_return_5bp": 0.01}}},
        }
        if repaired is not None:
            result["repaired_attempt_id"] = repaired
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

    add("z-run-earlier", "2026-09-08T05:00:00+00:00", "z-call", None)
    add("a-run-later", "2026-09-08T06:00:00+00:00", "a-call", "z-call")
    connection.commit()
    connection.close()

    detail = ResearchWorkspaceProjection(database, cycle_paths=()).experiment("exp-shared")
    assert detail["selection_semantics"] == "persisted_agent_audit_run_ordinal_then_tool_sequence"
    assert detail["attempt_count"] == 2
    assert [item["run_id"] for item in detail["attempts"]] == [
        "z-run-earlier",
        "a-run-later",
    ]
    assert detail["item"]["run_id"] == "a-run-later"
    assert detail["item"]["status"] == "repaired"
    assert detail["item"]["attempt_order"]["run_ordinal"] > detail["attempts"][0][
        "attempt_order"
    ]["run_ordinal"]
'''
path.write_text(text, encoding="utf-8")
