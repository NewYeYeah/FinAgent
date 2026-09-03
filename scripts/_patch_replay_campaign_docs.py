from pathlib import Path

bridge = Path("docs/guides/streaming-research-evidence-bridge.md")
text = bridge.read_text(encoding="utf-8")
old = """## 9. Next implementation boundary

After this bridge is closed, the next coherent engineering increment is **Replay Experiment Orchestration / Streaming-vs-Batch Research Campaign v1**: execute the existing B0/A0/R1 runners from persisted streaming evidence across deterministic replay fixtures and real bounded local U.S. slices, compare semantically equivalent streaming and batch inputs/results, and preserve every existing certification/Gate prerequisite.

That increment must still remain implementation/evidence preparation until current stage authority explicitly permits formal downstream research acceptance.
"""
new = """## 9. Follow-on campaign

**Replay Experiment Orchestration / Streaming-vs-Batch Research Campaign v1** is now implemented. It independently materializes accepted US-D2 batch bars/labels from the same bounded minute source used by `DatabaseReplaySource`, freezes streaming evidence, and requires exact canonical equality across five row slices plus B0/A0/R1 materialization/evaluation surfaces. The implementation also separates the feature-formation clock from the D2 raw 1m price-source clock in persisted label evidence.

See `docs/guides/replay-experiment-campaign.md` for the frozen sixteen parity surfaces, deterministic fixture identities, local bounded operator and authority boundary.

The next coherent engineering increment is **Bounded Real-Data Replay Campaign / Runtime Soak v1**. It remains implementation/evidence preparation until current stage authority explicitly permits formal downstream research acceptance.
"""
if text.count(old) != 1:
    raise SystemExit("streaming bridge next-boundary section did not match expected text")
bridge.write_text(text.replace(old, new, 1), encoding="utf-8")

changelog = Path("docs/development/changelog.md")
text = changelog.read_text(encoding="utf-8")
marker = "## 2026-09-03 — Streaming Feature / Strategy Integration v1 implementation closure\n"
if text.count(marker) != 1:
    raise SystemExit("changelog insertion marker not found exactly once")
entry = """## 2026-09-03 — Replay Experiment Orchestration / Streaming-vs-Batch Research Campaign v1 implementation closure

- implemented an engineering-only `ReplayExperimentCampaign` over one bounded minute source with independent streaming (`DatabaseReplaySource -> AlgorithmRunner -> USBaselineStreamingAlgorithm`) and accepted US-D2 batch (`SessionResampledMinuteStore -> SameSessionLabelStore`) paths;
- froze exact row-count + SHA-256 parity across five input slices (5m/60m, 15m/30m, 15m/60m, 15m/120m, 30m/60m) and eleven downstream B0/A0/R1 observation/diagnostic/evaluation surfaces, for sixteen mandatory unique parity checks with no tolerance-based pass;
- discovered and corrected a previously hidden clock conflation by retaining feature/bar formation `source_event_time` separately from optional D2 raw 1m `price_event_time`; new batch-backed evidence reproduces the formal D2 source clock while old v1 bridge documents remain backward-compatible;
- hardened the content-addressed campaign report so it requires the frozen five batch slices, all sixteen unique parity surfaces and the canonical B0 denominator, while persisting `formal_us_b0_operator_invoked=false`, `us_d3_certification_consumed=false` and all research/Agent-value/Alpha/execution/stage authority flags as false;
- added `scripts/run_replay_experiment_campaign.py` for bounded real local U.S. historical campaigns against frozen source revision `776328445b7ac6e7815ef3a483e9c8ded1eb6d56`, inventory `us-minute-inventory-c2cbf682b456f97eb613ed65`, cleaning stack `us-minute-cleaning-stack-a0d745a4a75d25a63e3a8244` and calendar `trading-calendar-03a9c29f566d6634aedbbbdc`, without invoking the formal stage-gated US-B0 operator;
- deterministic real DuckDB/Parquet fixture smoke accepted campaign `replay-experiment-campaign-35b80d37b1c36bd08c9eb6f1` with 16/16 parity checks, row counts 120/40/40/40/20 and no blockers;
- passed 55 focused campaign/bridge/streaming/B0/A0/R1 regressions, deterministic smoke, provider/mutation and authority guards, Ruff, strict mypy, py_compile, bridge backward-compatibility checks, generic project tests and documentation governance;
- retained `docs/status.toml` unchanged at US-D3: campaign parity proves implementation equivalence only and does not certify US-D3, formally admit B0/A0/R1, prove current U.S. market data, or grant CFD/PAPER/execution/live-capital authority.

"""
changelog.write_text(text.replace(marker, entry + marker, 1), encoding="utf-8")
