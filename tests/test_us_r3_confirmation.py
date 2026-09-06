from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from finagent.research.us_r3_completion import seal
from finagent.research.us_r3_confirmation import confirm_returns
from finagent.research.us_r3_economic_campaign import file_digest
from finagent.research.us_r3_inference import EvidenceDesign


def confirmation_fixture(root, *, positive=True, missing=False):
    protocol_path, model_path = root / "protocol.json", root / "model.json"
    protocol = seal(
        protocol_path,
        {
            "design": EvidenceDesign(
                effect_bps=5, planning_daily_sigma_bps=6.3, family_size=2
            ).to_dict()
        },
        "us-r3-completion-protocol-",
    )
    model = seal(
        model_path,
        {
            "protocol_id": protocol["evidence_id"],
            "frozen_at_utc": "2026-09-06T00:00:00+00:00",
            "members": [{"method": "manual", "run": 0}],
        },
        "r3-frozen-model-",
    )
    days = [(date(2027, 1, 1) + timedelta(days=i)).isoformat() for i in range(20)]
    values = [(0.01 if positive else -0.01) + (i % 3) * 0.001 for i in range(20)]
    if missing:
        values[3] = None
    returns = root / "returns.json"
    returns.write_text(
        json.dumps(
            {
                "model_id": model["evidence_id"],
                "sessions": days,
                "series": {"manual-0": values},
                "equal_weight_net_returns": [0.0] * 20,
            }
        )
    )
    receipt = root / "receipt.json"
    receipt.write_text(
        json.dumps(
            {
                "model_id": model["evidence_id"],
                "protocol_id": protocol["evidence_id"],
                "independent_reviewer_id": "synthetic-reviewer",
                "preregistered_at_utc": "2026-09-07T00:00:00+00:00",
                "not_previously_exposed": True,
                "point_in_time_universe_admitted": True,
                "cost_and_execution_evidence_admitted": True,
                "observations_start_utc": "2027-01-01T00:00:00+00:00",
                "observations_end_utc": "2027-01-21T00:00:00+00:00",
                "returns_sha256": file_digest(returns),
                "scheduled_sessions": days,
                "cost_bps": 5.0,
            }
        )
    )
    return {
        "model_path": model_path,
        "protocol_path": protocol_path,
        "receipt_path": receipt,
        "trusted_receipt_sha256": file_digest(receipt),
        "returns_path": returns,
        "output": root / "result.json",
    }


@pytest.mark.parametrize(
    "positive,missing,terminal",
    [
        (True, False, "CONFIRMED_POSITIVE"),
        (False, False, "CONFIRMED_NEGATIVE"),
        (True, True, "INSUFFICIENT_INDEPENDENT_EVIDENCE"),
    ],
)
def test_final_states_never_grant_authority(tmp_path, positive, missing, terminal):
    result = confirm_returns(**confirmation_fixture(tmp_path, positive=positive, missing=missing))
    assert result["findings"]["manual-0"]["terminal"] == terminal
    assert result["alpha_authority"] is False
    assert result["broker_authority"] is False


def test_untrusted_or_exposed_receipt_rejected_before_opening_final_data(tmp_path):
    args = confirmation_fixture(tmp_path)
    args["returns_path"].unlink()
    args["trusted_receipt_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="trust root"):
        confirm_returns(**args)
    receipt = json.loads(args["receipt_path"].read_text())
    receipt["not_previously_exposed"] = False
    args["receipt_path"].write_text(json.dumps(receipt))
    args["trusted_receipt_sha256"] = file_digest(args["receipt_path"])
    with pytest.raises(ValueError, match="admission missing"):
        confirm_returns(**args)


@pytest.mark.parametrize(
    "field,value",
    [
        ("observations_start_utc", "2025-01-01T00:00:00+00:00"),
        ("scheduled_sessions", ["2027-01-01"]),
        ("cost_bps", 0),
        ("preregistered_at_utc", "2027-01-22T00:00:00+00:00"),
    ],
)
def test_chronology_calendar_and_cost_cannot_be_rewritten(tmp_path, field, value):
    args = confirmation_fixture(tmp_path)
    receipt = json.loads(args["receipt_path"].read_text())
    receipt[field] = value
    args["receipt_path"].write_text(json.dumps(receipt))
    args["trusted_receipt_sha256"] = file_digest(args["receipt_path"])
    args["returns_path"].unlink()  # Admission must fail before any final-source access.
    with pytest.raises(ValueError):
        confirm_returns(**args)
