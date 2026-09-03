from pathlib import Path

root = Path(__file__).resolve().parents[1]
guide = root / "docs" / "guides" / "realtime-source-development-model.md"
changelog = root / "docs" / "development" / "changelog.md"

guide_text = guide.read_text(encoding="utf-8")
old_section = """## 10. Next implementation increment

The next coherent PR should implement **Streaming Source Harness v1**:

1. freeze `MarketDataSource` / `MarketDataSubscription` / `FeedTimingProfile` contracts;
2. implement `DatabaseReplaySource` on the existing DuckDB/Parquet U.S. minute plane;
3. support `1x`, accelerated, FAST and STEP pacing plus an explicit delayed-delivery profile;
4. feed replay output into the existing canonical realtime projector;
5. introduce an `AlgorithmRunner`/subscription boundary so algorithms cannot read DuckDB/MT5 provider objects directly;
6. wrap the existing MT5-M1 adapter as the live implementation of the same source boundary;
7. run differential contract tests showing DB replay and FX live reach the same downstream event/state API;
8. add delayed-profile tests that distinguish progressing-delay from stale/frozen data and enforce a strategy freshness budget;
9. preserve source-supported event types only—no synthetic bid/ask from OHLCV;
10. keep all outputs implementation/engineering-only until the existing stage and final target-broker gates are separately satisfied.

Acceptance for this increment is architectural and deterministic: source swapping must require configuration changes only, not algorithm changes."""
new_section = """## 10. Streaming Source Harness v1 implementation

Streaming Source Harness v1 is implemented as an engineering/runtime capability. It does **not** advance `docs/status.toml`, US-D3, broker/PAPER, execution or live-capital authority.

Implemented contracts and boundaries:

```text
MarketDataSource
MarketDataSubscription
FeedTimingProfile
FeedTimingClass: CURRENT / DELAYED / REPLAY / UNKNOWN
ReplayPacingMode: REALTIME / ACCELERATED / FAST / STEP
StrategyFreshnessBudget
DataAdmissibilityDecision
AlgorithmRunner
```

Implemented sources:

```text
DatabaseReplaySource
  existing bounded DuckDB/Parquet minute query plan
  -> batch streaming
  -> truthful canonical BarEvent only

MT5RealtimeSource
  existing read-only MT5 client + MT5 quote adapter
  -> canonical QuoteEvent polling
  -> no symbol selection or order mutation
```

The database replay source preserves historical `event_time`; deterministic replay delivery uses the source `available_at` plus the explicit feed-profile delay. Wall-clock pacing changes only when an event is emitted, not its canonical identity. FAST, REALTIME, accelerated and explicit STEP modes share the same event identities.

The algorithm boundary is provider-neutral: the projector observes every incoming canonical event, while `StrategyFreshnessBudget` independently controls whether an algorithm may act. A progressing ~900-second delayed profile therefore remains visible as healthy/progressing runtime data while being rejected for a 60-second decision budget. A non-progressing source additionally carries `source:not_progressing`.

The v1 implementation is regression-locked against real temporary DuckDB/Parquet input plus a fake read-only MT5 source. Provider-boundary guards prevent DuckDB/MT5 dependencies from leaking into `AlgorithmRunner`, and prevent `order_send()`, `symbol_select()` or market-book mutation surfaces from entering the source layer.

Deterministic engineering smoke identities for the frozen fixture are:

```text
replay profile       feed-timing-profile-5f111505a49fdfe6167eea17
replay run           algorithm-streaming-run-d7cee46c7d5cc51811d46a3d
replay semantic state realtime-semantic-state-ba1a416d1391aece7d40b363

delayed profile      feed-timing-profile-b2b8ce372ee25797dbe860ae
delayed run          algorithm-streaming-run-4a9020dc2d1dfa1b02da0c1e
```

These identities are development fixtures only. They prove canonical source substitution, deterministic replay and delayed-data gating; they do not prove U.S. current-market, CFD microstructure, broker-account or execution authority.

### Next implementation boundary

The next code increment should build **streaming feature/strategy integration** on top of this source harness rather than adding another provider-specific market-data path. The intended direction is incremental 1m -> 5m/15m/30m streaming aggregation, feature-state updates and existing B0/A0/R1 algorithm invocation through `AlgorithmRunner`, with database replay as the primary U.S. algorithm source and FX live as the connected runtime source. Final target-broker U.S. CFD remains the broker/source freeze surface."""
if guide_text.count(old_section) != 1:
    raise RuntimeError("unexpected realtime source guide v1 section")
guide.write_text(guide_text.replace(old_section, new_section, 1), encoding="utf-8")

changelog_text = changelog.read_text(encoding="utf-8")
anchor = "This file records **meaningful completed milestones**, not per-PR implementation detail. Git commits and pull requests are the detailed audit trail; frozen product interpretation belongs in `docs/releases/`.\n\n"
entry = """## 2026-09-03 — Streaming Source Harness v1 implementation closure

- froze provider-neutral `MarketDataSource`, `MarketDataSubscription`, `FeedTimingProfile`, replay pacing and strategy-freshness contracts so algorithms do not depend directly on DuckDB or MetaTrader5 provider objects;
- implemented bounded DuckDB batch streaming and `DatabaseReplaySource` over the admitted U.S. 1m Parquet Data Plane, preserving historical `event_time`, source `available_at`, deterministic delivery identity and truthful BarEvent-only semantics;
- implemented FAST, realtime, accelerated and explicit step replay modes without changing canonical event identity, and wrapped the existing read-only MT5 quote adapter in the same source/subscription surface for FX/live engineering use;
- implemented `AlgorithmRunner` so canonical projection/health state sees every event while strategy freshness gates decide independently whether an algorithm may act;
- retained progressing delayed feeds as a first-class `DELAYED` mode: the canonical 900-second fixture produces a 960-second 1m-bar event age and is rejected by the frozen 60-second source-delay / 120-second event-age test budget without being mislabeled frozen or disconnected;
- passed the dedicated 26-test source/realtime/MT5 regression, real temporary DuckDB/Parquet deterministic smoke, provider/mutation guards, Ruff, strict mypy, py_compile, US-D1 Data Plane, RT replay/projection and generic pytest/quality regressions;
- retained `docs/status.toml` and all U.S./broker authority boundaries unchanged: replay/FX/delayed fixtures prove engineering behavior only and do not satisfy US-D3, current U.S. market-data, CFD microstructure, PAPER, execution or live-capital acceptance.

"""
if changelog_text.count(anchor) != 1:
    raise RuntimeError("unexpected changelog introduction")
changelog.write_text(changelog_text.replace(anchor, anchor + entry, 1), encoding="utf-8")
print("Streaming Source Harness v1 completion docs updated")
