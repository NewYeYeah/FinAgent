"""Offline provider scenarios using real annual Parquet and the existing core."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from finagent.agents.r3_contracts import (
    DevelopmentRecord,
    DevelopmentScope,
    ResearchRuntimePolicy,
    canonical_json,
    decode_action,
    proposal_action,
)
from finagent.agents.r3_runtime import ResearchReply
from finagent.agents.r4_contracts import ALLOCATORS
from finagent.application.research_controller_host import R4ResearchAdmission
from finagent.domain.research import TimeRange
from finagent.research.market_state import (
    MarketFeatureConfig,
    MarketFeatures,
    build_market_features,
)
from finagent.research.market_state_gmm import fit_market_state, project_market_state
from finagent.research.us_r3_alpha_catalog import build_us_r3_executable_frontier_candidates
from tests.adaptive_allocator_fixture import portfolio_inputs


class Clock:
    def __init__(self):
        self.value = datetime(2026, 9, 6, 12, tzinfo=UTC).timestamp()

    def __call__(self):
        self.value += 0.01
        return self.value


def admission_fixture(root):
    inputs = portfolio_inputs(root)
    fold = inputs["folds"][0]
    window = TimeRange(fold.train.start, fold.state_fit_end)
    sessions = inputs["source"].read(window)
    config = MarketFeatureConfig("A0")
    features = MarketFeatures(
        inputs["source"].identity,
        config,
        tuple(
            row
            for s in sessions
            for row in build_market_features(s, inputs["source"].identity, config).rows
        ),
    )
    model = fit_market_state(features, window)
    session = inputs["source"].read(fold.evaluation)[0]
    state = project_market_state(
        model,
        build_market_features(session, inputs["source"].identity, config),
        as_of=fold.evaluation.end,
    )[-1]
    literature = DevelopmentRecord(
        "r4-fixture",
        "curated-literature",
        "literature",
        canonical_json(
            {
                "title": "Controlled fixture hypothesis",
                "url": "https://example.invalid/research",
                "summary": "An explicit test resource; no financial evidence.",
            }
        ),
    )
    scope = DevelopmentScope(
        "r4-fixture",
        (literature,),
        inputs["source"].identity.identity,
        "existing-factor-library-evaluator",
    )
    return R4ResearchAdmission(
        inputs["source"],
        inputs["folds"],
        inputs["library"],
        inputs["economics"],
        model,
        state,
        scope,
        datetime(2026, 9, 6, tzinfo=UTC),
    ), inputs


def action(tool, **arguments):
    return canonical_json(
        {"schema_version": "finagent.r4-action.v1", "tool": tool, "arguments": arguments}
    )


class ScriptedProvider:
    def __init__(self, steps):
        self.steps = steps
        self.requests = []

    def respond(self, request):
        self.requests.append(request)
        context = json.loads(request.context_json)
        step = self.steps[context["attempt"] - 1]
        if isinstance(step, Exception):
            raise step
        return ResearchReply(step(context) if callable(step) else step, 100, 10)


def selection_steps(ids):
    return [
        action("inspect_factor_library", offset=0),
        action("inspect_market_state"),
        action("propose_factor_set", factor_ids=ids[:2], hypothesis_id="diversify"),
        action("propose_allocator", allocator=ALLOCATORS[3]),
        lambda c: action(
            "evaluate_portfolio",
            factor_set_id=c["state"]["factor_set"]["factor_set_id"],
            allocator_proposal_id=c["state"]["allocator"]["allocator_proposal_id"],
            hypothesis_id="diversify",
        ),
        lambda c: action(
            "compare_experiments", experiment_ids=[c["state"]["latest_experiment"]["experiment_id"]]
        ),
        action(
            "record_decision",
            critique="Engineering fixture establishes no independent financial evidence.",
            next_action="Stop this fixture and recommend no candidate.",
        ),
        action(
            "finalize_candidate",
            recommendation="none",
            factor_set_id=None,
            allocator_proposal_id=None,
            experiment_ids=[],
            decision="NO_CANDIDATE_RECOMMENDED: controlled fixture only.",
        ),
    ]


def factor_steps(admission, ids):
    candidate = build_us_r3_executable_frontier_candidates()[0]
    proposal = json.loads(proposal_action(candidate.graph, candidate.hypothesis))["arguments"]
    proposal["nodes"].append(
        {"node_id": "inverse", "operator": "NEGATE", "inputs": [proposal["output_node_id"]]}
    )
    proposal["output_node_id"] = "inverse"
    proposal["hypothesis"]["summary"] = "Inverted development fixture hypothesis"
    new_id = (
        decode_action(
            canonical_json(
                {
                    "schema_version": "finagent.us-r3-agent-action.v2",
                    "tool": "validate_factor",
                    "arguments": proposal,
                }
            )
        )
        .proposal.hypothesis()
        .candidate_id
    )
    return [
        lambda c: action(
            "read_literature",
            record_id=next(r["record_id"] for r in c["resources"] if r["kind"] == "literature"),
        ),
        action("propose_factor", **proposal),
        action("evaluate_factor", candidate_id=new_id),
        action("propose_factor_set", factor_ids=[ids[0], new_id], hypothesis_id="new-hypothesis"),
        action("propose_allocator", allocator="equal_weight"),
        lambda c: action(
            "evaluate_portfolio",
            factor_set_id=c["state"]["factor_set"]["factor_set_id"],
            allocator_proposal_id=c["state"]["allocator"]["allocator_proposal_id"],
            hypothesis_id="new-hypothesis",
        ),
        action(
            "finalize_candidate",
            recommendation="none",
            factor_set_id=None,
            allocator_proposal_id=None,
            experiment_ids=[],
            decision="No candidate; retrospective development fixture.",
        ),
    ]


def comparison_steps(ids):
    initial = selection_steps(ids)
    return [
        *initial[:5],
        initial[4],
        action("propose_factor_set", factor_ids=ids, hypothesis_id="diversify"),
        initial[4],
        action("inspect_experiment_history", offset=0),
        lambda c: action(
            "compare_experiments",
            experiment_ids=[
                r["experiment_id"]
                for r in c["feedback"][-1]["attempts"]
                if r["outcome"] == "PORTFOLIO_EVALUATED"
            ],
        ),
        action(
            "record_decision",
            critique="Two controlled development experiments; no independent evidence.",
            next_action="Propose an engineering-only development candidate and stop.",
        ),
        action("propose_allocator", allocator="rolling_net_return"),
        lambda c: action(
            "finalize_candidate",
            recommendation="candidate",
            factor_set_id=c["state"]["factor_set"]["factor_set_id"],
            allocator_proposal_id=c["state"]["allocator"]["allocator_proposal_id"],
            experiment_ids=[c["state"]["latest_experiment"]["experiment_id"]],
            decision="Development candidate proposed for interface verification only; no independent financial claim.",
        ),
    ]


def fixture_policy(**changes):
    config = {
        "maximum_attempts": 30,
        "maximum_attempts_per_slot": 30,
        "maximum_evaluations": 4,
        "maximum_tokens": 262144,
        "tokens_per_call": 32768,
        "maximum_cost_microusd": 1000000,
        "call_timeout_seconds": 120,
    }
    return ResearchRuntimePolicy(**{**config, **changes})
