from __future__ import annotations

from collections.abc import Mapping

from finagent.research.us_r1_gate import (
    USR1AlphaGatePolicy,
    canonical_us_r1_alpha_gate_policy,
)
from finagent.research.us_r1_protocol import (
    USR1ResearchProtocol,
    canonical_us_r1_research_protocol,
)


def validate_us_r1_research_protocol(
    document: Mapping[str, object],
) -> USR1ResearchProtocol:
    expected = canonical_us_r1_research_protocol()
    if dict(document) != expected.to_dict():
        raise ValueError("US-R1 research protocol does not match the exact frozen canonical protocol")
    return expected


def validate_us_r1_protocol_document(
    document: Mapping[str, object],
) -> USR1ResearchProtocol:
    """Compatibility name for formal runners that validate a persisted protocol document."""

    return validate_us_r1_research_protocol(document)


def validate_us_r1_alpha_gate_policy(
    document: Mapping[str, object],
) -> USR1AlphaGatePolicy:
    expected = canonical_us_r1_alpha_gate_policy()
    if dict(document) != expected.to_dict():
        raise ValueError("US-R1 Alpha Gate policy does not match the exact frozen canonical policy")
    return expected
