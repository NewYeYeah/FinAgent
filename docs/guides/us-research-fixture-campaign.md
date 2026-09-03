# U.S. Research Fixture Campaign

This guide defines the offline deterministic development campaign for the current period in which the real U.S. MT5 operator evidence tracked by Issue #125 is unavailable.

The campaign validates implementation behavior only. It does **not** substitute synthetic data, FX quotes, fixture identities, or deterministic expected outcomes for real U.S. research or broker evidence.

## Authority boundary

`docs/status.toml` remains the only project-stage authority and remains at US-D3 until the real evidence chain is accepted.

A passing fixture campaign means only:

- US-B0 calculation code can recover a deliberately injected cross-sectional signal and reject an engineered technical data failure;
- US-A0 MANUAL / PROGRAMMATIC / AGENT generation and arm-result contracts execute deterministically under equal PILOT budgets without any external LLM call;
- US-R1 HAC, session-block bootstrap, multiplicity and frozen Alpha Gate distinguish a deliberately injected robust signal, a null process and a technical failure;
- the downstream implementation frontier is ready for further offline development.

A passing fixture campaign does **not** mean:

- US-D3 passed;
- the U.S. EngineeringUniverse is accepted;
- US-B0 has authoritative market evidence;
- the Agent Value Gate passed;
- Alpha exists;
- execution/PAPER/live authority exists.

All campaign artifacts therefore carry false `status_authority`, `stage_exit_authority`, `agent_value_gate_authority`, `alpha_authority`, `execution_authority`, and `live_capital_authority` fields.

## Frozen scenarios

The campaign always runs the following three scenarios in order.

### KNOWN_ALPHA

B0 receives a 12-asset cross-section in which the first canonical baseline feature is deliberately aligned with the forward label. A0 receives deterministic MANUAL and seeded PROGRAMMATIC runs plus a deterministic AGENT-shaped structured run whose candidates are structurally novel relative to both controls. R1 receives three folds of positive RankIC, positive gross long-short return, adequate coverage, frequency consistency and decay consistency.

Expected engineering result:

```text
B0 anchor RankIC > 0.95
A0 fixture outcome = AGENT_BETTER_FIXTURE
R1 terminal = ROBUST_FACTOR_FAMILY
```

The R1 terminal is a synthetic ground-truth test of the real gate implementation. The campaign report itself has `alpha_authority=false`.

### KNOWN_NULL

B0 alternates the sign of the label so the anchor feature has approximately zero mean RankIC. A0 deliberately assigns the AGENT-shaped run lower quality than the controls. R1 alternates positive and negative RankIC around zero.

Expected engineering result:

```text
abs(B0 anchor RankIC) < 0.05
A0 fixture outcome = NO_AGENT_ADVANTAGE_FIXTURE
R1 terminal = NO_ROBUST_FACTOR_FAMILY
```

### TECHNICAL_FAILURE

B0 uses only four assets while the frozen fixture run requires a minimum cross-section of ten. A0 carries an explicit synthetic evaluation blocker. R1 carries an explicit missing-bundle technical blocker.

Expected engineering result:

```text
B0 valid candidate count = 0
A0 fixture outcome = SYSTEM_FAILURE_FIXTURE
R1 terminal = SYSTEM_FAILURE
```

This scenario verifies that technical failure is not silently converted into a negative research result or a passing gate.

## Local Windows / Conda workflow

Use the normal workstation environment rather than rewriting workstation commands around the CI resolver.

```powershell
conda activate finagent
cd D:\PythonWorkspace\FinAgent

git fetch origin
git checkout research-fixture-campaign
git pull --ff-only
```

Run the focused behavior regression:

```powershell
pytest -q tests\test_us_research_fixture_campaign.py
```

Run the deterministic CLI campaign:

```powershell
python scripts\run_us_research_fixture_campaign.py `
  --generated-at 2026-09-03T06:30:00+00:00 `
  --output reports\development\us_research_fixture_campaign.json
```

A passing report must contain:

```text
passed = true
KNOWN_ALPHA.R1 = ROBUST_FACTOR_FAMILY
KNOWN_NULL.R1 = NO_ROBUST_FACTOR_FAMILY
TECHNICAL_FAILURE.R1 = SYSTEM_FAILURE
real_us_market_evidence_substituted = false
status_authority = false
stage_exit_authority = false
agent_value_gate_authority = false
alpha_authority = false
```

Run focused static checks:

```powershell
ruff check `
  src\finagent\research\us_fixture_campaign.py `
  scripts\run_us_research_fixture_campaign.py `
  tests\test_us_research_fixture_campaign.py

mypy --strict `
  src\finagent\research\us_fixture_campaign.py `
  scripts\run_us_research_fixture_campaign.py

python -m py_compile `
  src\finagent\research\us_fixture_campaign.py `
  scripts\run_us_research_fixture_campaign.py
```

## Relationship to the real research chain

The implementation frontier and authority frontier remain separate:

```text
Authority frontier
US-D3 -- blocked on Issue #125 real U.S. evidence

Implementation frontier
US-B0 -> US-A0 -> US-R1 -- fixture validated
```

When the real U.S. evidence becomes available, the fixture campaign is not promoted or re-labeled. The real chain must still execute independently:

```text
real S2 EngineeringUniverse
-> U.S.-specific MT5-D0
-> S3 certification/review
-> US-D3 governance closure
-> real US-B0
-> real US-A0
-> real US-R1
```

Only those authoritative runs may control later research, Alpha, historical execution or live progression.
