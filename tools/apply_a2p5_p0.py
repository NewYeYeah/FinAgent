from __future__ import annotations

import re
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


root = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# A-share universe split warm-up
# ---------------------------------------------------------------------------
path = root / "src/finagent/research/ashare_universe.py"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from datetime import date, datetime\n",
    "from datetime import date, datetime, timedelta\n",
    "universe datetime import",
)
text = replace_once(
    text,
    "from finagent.domain.research import DatasetRequest\n",
    "from finagent.domain.research import DatasetRequest, TimeRange\n",
    "universe TimeRange import",
)
text = replace_once(
    text,
    "    min_liquidity_observations: int = 10\n",
    "    min_liquidity_observations: int = 10\n"
    "    liquidity_warmup_calendar_days: int = 120\n",
    "universe warmup config field",
)
text = replace_once(
    text,
    "        if not 1 <= self.min_liquidity_observations <= self.liquidity_lookback:\n"
    "            raise ValueError(\"min_liquidity_observations must be in [1, liquidity_lookback]\")\n",
    "        if not 1 <= self.min_liquidity_observations <= self.liquidity_lookback:\n"
    "            raise ValueError(\"min_liquidity_observations must be in [1, liquidity_lookback]\")\n"
    "        if self.liquidity_warmup_calendar_days < 1:\n"
    "            raise ValueError(\"liquidity_warmup_calendar_days must be >= 1\")\n",
    "universe warmup validation",
)
text = replace_once(
    text,
    "class AshareUniverseSplitSummary:\n"
    "    split_name: str\n"
    "    timestamps: int\n"
    "    assets: int\n"
    "    eligible_cells: int\n"
    "    average_eligible_assets: float\n"
    "    minimum_eligible_assets: int\n"
    "    maximum_eligible_assets: int\n",
    "class AshareUniverseSplitSummary:\n"
    "    split_name: str\n"
    "    timestamps: int\n"
    "    assets: int\n"
    "    warmup_timestamps: int\n"
    "    first_session_eligible_assets: int\n"
    "    eligible_cells: int\n"
    "    average_eligible_assets: float\n"
    "    minimum_eligible_assets: int\n"
    "    maximum_eligible_assets: int\n",
    "universe summary fields",
)
text = replace_once(
    text,
    "            \"timestamps\": self.timestamps,\n"
    "            \"assets\": self.assets,\n"
    "            \"eligible_cells\": self.eligible_cells,\n",
    "            \"timestamps\": self.timestamps,\n"
    "            \"assets\": self.assets,\n"
    "            \"warmup_timestamps\": self.warmup_timestamps,\n"
    "            \"first_session_eligible_assets\": self.first_session_eligible_assets,\n"
    "            \"eligible_cells\": self.eligible_cells,\n",
    "universe summary serialization",
)
text = replace_once(
    text,
    "                \"min_liquidity_observations\": self.config.min_liquidity_observations,\n",
    "                \"min_liquidity_observations\": self.config.min_liquidity_observations,\n"
    "                \"liquidity_warmup_calendar_days\": (\n"
    "                    self.config.liquidity_warmup_calendar_days\n"
    "                ),\n",
    "universe report warmup serialization",
)
new_policy = '''class AshareResearchUniversePolicy:
    """Build a PIT research universe with split-independent rolling liquidity.

    Every requested split receives a hidden pre-split panel. The warm-up panel is
    used only to initialize trailing liquidity and is never returned as a research
    split or exposed as validation evidence. This prevents split boundaries from
    manufacturing zero-eligible sessions.
    """

    def __init__(self, config: AshareResearchUniversePolicyConfig) -> None:
        self.config = config

    def build(
        self,
        adapter,
        request: DatasetRequest,
        *,
        candidate_selection_id: str,
    ) -> tuple[AshareResearchUniverseProvider, AshareResearchUniverseReport]:
        missing = set(self.config.required_features) - set(adapter.supported_features)
        if missing:
            raise ValueError(f"local A-share adapter lacks universe-policy fields: {sorted(missing)}")

        policy_splits: dict[str, TimeRange] = {}
        warmup_names: dict[str, str] = {}
        for split_name, split_range in request.splits.items():
            warmup_name = f"__warmup__:{split_name}"
            if warmup_name in request.splits:
                raise ValueError(f"reserved universe-policy split name: {warmup_name!r}")
            warmup_names[split_name] = warmup_name
            policy_splits[warmup_name] = TimeRange(
                split_range.start - timedelta(days=self.config.liquidity_warmup_calendar_days),
                split_range.start,
            )
            policy_splits[split_name] = split_range

        policy_request = DatasetRequest(
            universe=request.universe,
            features=self.config.required_features,
            labels=request.labels,
            splits=policy_splits,
            dataset_id=f"{request.dataset_id}-universe-policy",
            metadata={
                **dict(request.metadata),
                "candidate_selection_id": candidate_selection_id,
                "purpose": "A-share PIT research universe policy with split warm-up",
            },
        )
        dataset = adapter.build_dataset(policy_request)
        schedule: dict[datetime, frozenset[AssetId]] = {}
        summaries: dict[str, AshareUniverseSplitSummary] = {}
        digest = hashlib.sha256()
        digest.update(adapter.data_version.encode())
        digest.update(candidate_selection_id.encode())
        digest.update(
            _canonical_json(
                {
                    "min_listed_days": self.config.min_listed_days,
                    "exclude_st": self.config.exclude_st,
                    "min_close": self.config.min_close,
                    "min_median_amount_cny": self.config.min_mian_amount_cny,
                    "liquidity_lookback": self.config.liquidity_lookback,
                    "min_liquidity_observations": self.config.min_liquidity_observations,
                    "liquidity_warmup_calendar_days": (
                        self.config.liquidity_warmup_calendar_days
                    ),
                }
            ).encode()
        )

        for split_name in request.splits:
            panel = dataset.get_split(split_name)
            warmup = dataset.get_split(warmup_names[split_name])
            if warmup.assets != panel.assets or warmup.feature_names != panel.feature_names:
                raise ValueError("universe-policy warm-up panel is not aligned")

            base = np.asarray(panel.eligibility_mask, dtype=bool)
            close = panel.feature_panel("close")
            amount = panel.feature_panel("amount")
            warmup_amount = warmup.feature_panel("amount")
            listed_days = panel.feature_panel("listed_days")
            st = panel.feature_panel("is_st") if self.config.exclude_st else None

            listed_ok = np.isfinite(listed_days) & (listed_days >= self.config.min_listed_days)
            close_ok = np.isfinite(close) & (close >= self.config.min_close)
            st_ok = np.ones_like(base, dtype=bool)
            if st is not None:
                st_ok = np.isfinite(st) & (st <= 0.0)

            amount_history = np.concatenate((warmup_amount, amount), axis=0)
            offset = warmup.n_times
            liquidity_ok = np.zeros_like(base, dtype=bool)
            for row in range(panel.n_times):
                history_end = offset + row + 1
                history_start = max(0, history_end - self.config.liquidity_lookback)
                window = amount_history[history_start:history_end]
                for asset_index in range(panel.n_assets):
                    values = window[:, asset_index]
                    values = values[np.isfinite(values)]
                    if len(values) < self.config.min_liquidity_observations:
                        continue
                    liquidity_ok[row, asset_index] = (
                        float(np.median(values)) >= self.config.min_median_amount_cny
                    )

            final = base & listed_ok & close_ok & st_ok & liquidity_ok
            rejected = {
                "base_ineligible": int((~base).sum()),
                "listed_days": int((base & ~listed_ok).sum()),
                "price": int((base & ~close_ok).sum()),
                "st": int((base & ~st_ok).sum()),
                "liquidity": int((base & ~liquidity_ok).sum()),
            }
            counts = final.sum(axis=1)
            summaries[split_name] = AshareUniverseSplitSummary(
                split_name=split_name,
                timestamps=panel.n_times,
                assets=panel.n_assets,
                warmup_timestamps=warmup.n_times,
                first_session_eligible_assets=int(counts[0]),
                eligible_cells=int(final.sum()),
                average_eligible_assets=float(np.mean(counts)),
                minimum_eligible_assets=int(np.min(counts)),
                maximum_eligible_assets=int(np.max(counts)),
                rejected_counts=rejected,
            )
            for row, timestamp in enumerate(panel.timestamps):
                schedule[timestamp] = frozenset(
                    asset
                    for asset_index, asset in enumerate(panel.assets)
                    if final[row, asset_index]
                )
            digest.update(split_name.encode())
            digest.update(str(warmup.n_times).encode())
            digest.update("|".join(timestamp.isoformat() for timestamp in panel.timestamps).encode())
            digest.update(final.tobytes(order="C"))

        data_version = f"ashare-universe-policy-{digest.hexdigest()[:24]}"
        report = AshareResearchUniverseReport(
            data_version=data_version,
            candidate_selection_id=candidate_selection_id,
            config=self.config,
            splits=summaries,
        )
        return AshareResearchUniverseProvider(schedule, data_version=data_version), report
'''
text, count = re.subn(r"class AshareResearchUniversePolicy:\n[\s\S]*\Z", new_policy, text)
if count != 1:
    raise RuntimeError(f"universe policy class replacement: expected one match, found {count}")
path.write_text(text, encoding="utf-8")

path = root / "scripts/run_local_ashare_factor_research.py"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "            min_liquidity_observations=int(\n"
    "                values.get(\"policy_min_liquidity_observations\", 10)\n"
    "            ),\n",
    "            min_liquidity_observations=int(\n"
    "                values.get(\"policy_min_liquidity_observations\", 10)\n"
    "            ),\n"
    "            liquidity_warmup_calendar_days=int(\n"
    "                values.get(\"policy_liquidity_warmup_calendar_days\", 120)\n"
    "            ),\n",
    "A2 CLI warmup config",
)
path.write_text(text, encoding="utf-8")

# ---------------------------------------------------------------------------
# A-share acceptance semantics and stability evidence
# ---------------------------------------------------------------------------
path = root / "src/finagent/research/ashare_factor_acceptance.py"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from .factor_quant import (\n"
    "    FactorEnsembleSelection,\n"
    "    FactorEnsembleSelector,\n"
    "    FactorQuantAnalyzer,\n"
    "    FactorQuantCandidateReport,\n"
    "    FactorQuantFamilyReport,\n"
    ")\n",
    "from .factor_quant import (\n"
    "    FactorEnsembleSelection,\n"
    "    FactorEnsembleSelector,\n"
    "    FactorQuantAnalyzer,\n"
    "    FactorQuantCandidateReport,\n"
    "    FactorQuantFamilyReport,\n"
    ")\n"
    "from .factor_stability import (\n"
    "    FactorCandidateStabilityReport,\n"
    "    FactorFamilyStabilityReport,\n"
    "    FactorStabilityAnalyzer,\n"
    "    FactorStabilityConfig,\n"
    ")\n",
    "acceptance stability imports",
)
comparison_block = '''@dataclass(frozen=True, slots=True)
class AshareFactorValidationComparison:
    best_single_feature_digest: str
    best_single_direction: int
    best_single_raw_rank_icir: float
    best_single_rank_icir: float
    ensemble_rank_icir: float
    ensemble_minus_best_single_rank_icir: float
    absolute_rank_icir_magnitude_delta: float
    best_single_raw_long_short_sharpe: float
    best_single_long_short_sharpe: float
    ensemble_long_short_sharpe: float
    ensemble_minus_best_single_long_short_sharpe: float
    absolute_long_short_sharpe_magnitude_delta: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "best_single_feature_digest",
            require_non_empty(self.best_single_feature_digest, "best_single_feature_digest"),
        )
        if self.best_single_direction not in {-1, 1}:
            raise ValueError("best_single_direction must be -1 or 1")
        values = (
            self.best_single_raw_rank_icir,
            self.best_single_rank_icir,
            self.ensemble_rank_icir,
            self.ensemble_minus_best_single_rank_icir,
            self.absolute_rank_icir_magnitude_delta,
            self.best_single_raw_long_short_sharpe,
            self.best_single_long_short_sharpe,
            self.ensemble_long_short_sharpe,
            self.ensemble_minus_best_single_long_short_sharpe,
            self.absolute_long_short_sharpe_magnitude_delta,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("validation comparison metrics must be finite")

    def to_dict(self) -> dict[str, object]:
        return {
            "best_single_feature_digest": self.best_single_feature_digest,
            "best_single_direction": self.best_single_direction,
            "best_single_raw_rank_icir": self.best_single_raw_rank_icir,
            "best_single_rank_icir": self.best_single_rank_icir,
            "ensemble_rank_icir": self.ensemble_rank_icir,
            "ensemble_minus_best_single_rank_icir": self.ensemble_minus_best_single_rank_icir,
            "absolute_rank_icir_magnitude_delta": self.absolute_rank_icir_magnitude_delta,
            "best_single_raw_long_short_sharpe": self.best_single_raw_long_short_sharpe,
            "best_single_long_short_sharpe": self.best_single_long_short_sharpe,
            "ensemble_long_short_sharpe": self.ensemble_long_short_sharpe,
            "ensemble_minus_best_single_long_short_sharpe": self.ensemble_minus_best_single_long_short_sharpe,
            "absolute_long_short_sharpe_magnitude_delta": self.absolute_long_short_sharpe_magnitude_delta,
            "comparison_semantics": "development-frozen direction; signed deltas",
        }


@dataclass(frozen=True, slots=True)
class AshareResearchVerdictPolicy:
    min_validation_rank_icir: float = 0.0
    min_validation_long_short_sharpe: float = 0.0
    max_hac_pvalue: float = 0.05
    max_bootstrap_pvalue: float = 0.05

    def __post_init__(self) -> None:
        values = (
            self.min_validation_rank_icir,
            self.min_validation_long_short_sharpe,
            self.max_hac_pvalue,
            self.max_bootstrap_pvalue,
        )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("research verdict policy must be finite")
        if not 0.0 <= self.max_hac_pvalue <= 1.0:
            raise ValueError("max_hac_pvalue must be in [0, 1]")
        if not 0.0 <= self.max_bootstrap_pvalue <= 1.0:
            raise ValueError("max_bootstrap_pvalue must be in [0, 1]")

    def to_dict(self) -> dict[str, object]:
        return {
            "min_validation_rank_icir": self.min_validation_rank_icir,
            "min_validation_long_short_sharpe": self.min_validation_long_short_sharpe,
            "max_hac_pvalue": self.max_hac_pvalue,
            "max_bootstrap_pvalue": self.max_bootstrap_pvalue,
        }


@dataclass(frozen=True, slots=True)
class AshareResearchOutcome:
    status: str
    ensemble_validation_passed: bool
    promotion_eligible: bool
    reason_codes: tuple[str, ...]
    policy: AshareResearchVerdictPolicy

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", require_non_empty(self.status, "status"))
        if not self.reason_codes:
            raise ValueError("research outcome requires reason codes")
        object.__setattr__(
            self,
            "reason_codes",
            tuple(require_non_empty(value, "reason code") for value in self.reason_codes),
        )
        if self.promotion_eligible:
            raise ValueError("A2 cannot be promotion eligible before A-share execution certification")

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "ensemble_validation_passed": self.ensemble_validation_passed,
            "promotion_eligible": self.promotion_eligible,
            "reason_codes": list(self.reason_codes),
            "policy": self.policy.to_dict(),
        }
'''
text, count = re.subn(
    r"@dataclass\(frozen=True, slots=True\)\nclass AshareFactorValidationComparison:[\s\S]*?(?=@dataclass\(frozen=True, slots=True\)\nclass AshareFactorResearchAcceptanceResult:)",
    comparison_block + "\n\n",
    text,
)
if count != 1:
    raise RuntimeError(f"acceptance comparison replacement: expected one match, found {count}")
text = replace_once(
    text,
    "    validation_report: FactorQuantFamilyReport\n"
    "    validation_ensemble: FactorQuantCandidateReport\n"
    "    validation_comparison: AshareFactorValidationComparison\n",
    "    validation_report: FactorQuantFamilyReport\n"
    "    validation_ensemble: FactorQuantCandidateReport\n"
    "    validation_comparison: AshareFactorValidationComparison\n"
    "    development_stability: FactorFamilyStabilityReport\n"
    "    validation_stability: FactorFamilyStabilityReport\n"
    "    validation_ensemble_stability: FactorCandidateStabilityReport\n"
    "    research_outcome: AshareResearchOutcome\n",
    "acceptance result stability fields",
)
text = replace_once(
    text,
    "        if self.validation_ensemble.feature_digest != self.frozen_ensemble.ensemble_id:\n"
    "            raise ValueError(\"validation ensemble identity differs from frozen ensemble\")\n",
    "        if self.validation_ensemble.feature_digest != self.frozen_ensemble.ensemble_id:\n"
    "            raise ValueError(\"validation ensemble identity differs from frozen ensemble\")\n"
    "        if {candidate.feature_digest for candidate in self.development_stability.candidates} != candidate_digests:\n"
    "            raise ValueError(\"development stability denominator differs from candidates\")\n"
    "        if {candidate.feature_digest for candidate in self.validation_stability.candidates} != candidate_digests:\n"
    "            raise ValueError(\"validation stability denominator differs from candidates\")\n"
    "        if self.validation_ensemble_stability.feature_digest != self.frozen_ensemble.ensemble_id:\n"
    "            raise ValueError(\"ensemble stability identity differs from frozen ensemble\")\n",
    "acceptance result denominator checks",
)
text = replace_once(
    text,
    "            \"schema_version\": \"finagent.ashare-factor-research-acceptance.v1\",\n",
    "            \"schema_version\": \"finagent.ashare-factor-research-acceptance.v2\",\n",
    "acceptance schema version",
)
text = replace_once(
    text,
    "            \"passed\": True,\n"
    "            \"data_version\": self.data_version,\n",
    "            # Backward-compatible system-completion alias. Research validity is\n"
    "            # reported separately and can fail while the workflow succeeds.\n"
    "            \"passed\": True,\n"
    "            \"system_acceptance\": {\"passed\": True, \"status\": \"PASS\"},\n"
    "            \"research_outcome\": self.research_outcome.to_dict(),\n"
    "            \"data_version\": self.data_version,\n",
    "acceptance verdict serialization",
)
text = replace_once(
    text,
    "            \"validation_comparison\": self.validation_comparison.to_dict(),\n"
    "            \"reserve\": {\n",
    "            \"validation_comparison\": self.validation_comparison.to_dict(),\n"
    "            \"development_stability\": self.development_stability.to_dict(),\n"
    "            \"validation_stability\": self.validation_stability.to_dict(),\n"
    "            \"validation_ensemble_stability\": self.validation_ensemble_stability.to_dict(),\n"
    "            \"reserve\": {\n",
    "acceptance stability serialization",
)
text = replace_once(
    text,
    "        selector: FactorEnsembleSelector,\n"
    "    ) -> None:\n",
    "        selector: FactorEnsembleSelector,\n"
    "        stability_config: FactorStabilityConfig = FactorStabilityConfig(),\n"
    "        verdict_policy: AshareResearchVerdictPolicy = AshareResearchVerdictPolicy(),\n"
    "    ) -> None:\n",
    "acceptance engine init signature",
)
text = replace_once(
    text,
    "        self.development_analyzer = development_analyzer\n"
    "        self.validation_analyzer = validation_analyzer\n"
    "        self.selector = selector\n",
    "        self.development_analyzer = development_analyzer\n"
    "        self.validation_analyzer = validation_analyzer\n"
    "        self.selector = selector\n"
    "        self.development_stability_analyzer = FactorStabilityAnalyzer(\n"
    "            development_analyzer, config=stability_config\n"
    "        )\n"
    "        self.validation_stability_analyzer = FactorStabilityAnalyzer(\n"
    "            validation_analyzer, config=stability_config\n"
    "        )\n"
    "        self.verdict_policy = verdict_policy\n",
    "acceptance engine stability analyzers",
)
comparison_methods = '''    @staticmethod
    def _development_direction(candidate: FactorQuantCandidateReport) -> int:
        metric = candidate.primary.rank_ic
        if abs(metric) <= 1e-15:
            metric = candidate.primary.pearson_ic
        return 1 if metric >= 0 else -1

    @classmethod
    def _comparison(
        cls,
        development: FactorQuantFamilyReport,
        validation: FactorQuantFamilyReport,
        ensemble: FactorQuantCandidateReport,
    ) -> AshareFactorValidationComparison:
        oriented: list[tuple[float, str, int, FactorQuantCandidateReport]] = []
        for candidate in validation.candidates:
            direction = cls._development_direction(development.candidate(candidate.feature_digest))
            oriented.append(
                (
                    direction * candidate.primary.rank_icir,
                    candidate.feature_digest,
                    direction,
                    candidate,
                )
            )
        best_oriented_rank_icir, _, direction, best = max(
            oriented,
            key=lambda value: (value[0], value[1]),
        )
        raw_best_rank_icir = best.primary.rank_icir
        raw_best_sharpe = best.quantile_diagnostics.long_short_sharpe
        oriented_best_sharpe = direction * raw_best_sharpe
        ensemble_rank_icir = ensemble.primary.rank_icir
        ensemble_sharpe = ensemble.quantile_diagnostics.long_short_sharpe
        return AshareFactorValidationComparison(
            best_single_feature_digest=best.feature_digest,
            best_single_direction=direction,
            best_single_raw_rank_icir=raw_best_rank_icir,
            best_single_rank_icir=best_oriented_rank_icir,
            ensemble_rank_icir=ensemble_rank_icir,
            ensemble_minus_best_single_rank_icir=ensemble_rank_icir - best_oriented_rank_icir,
            absolute_rank_icir_magnitude_delta=abs(ensemble_rank_icir) - abs(best_oriented_rank_icir),
            best_single_raw_long_short_sharpe=raw_best_sharpe,
            best_single_long_short_sharpe=oriented_best_sharpe,
            ensemble_long_short_sharpe=ensemble_sharpe,
            ensemble_minus_best_single_long_short_sharpe=ensemble_sharpe - oriented_best_sharpe,
            absolute_long_short_sharpe_magnitude_delta=abs(ensemble_sharpe) - abs(oriented_best_sharpe),
        )

    def _research_outcome(
        self,
        ensemble: FactorQuantCandidateReport,
        stability: FactorCandidateStabilityReport,
    ) -> AshareResearchOutcome:
        policy = self.verdict_policy
        reasons: list[str] = []
        if ensemble.primary.rank_icir <= policy.min_validation_rank_icir:
            reasons.append("ENSEMBLE_RANK_ICIR_BELOW_THRESHOLD")
        if ensemble.quantile_diagnostics.long_short_sharpe <= policy.min_validation_long_short_sharpe:
            reasons.append("ENSEMBLE_LONG_SHORT_SHARPE_BELOW_THRESHOLD")
        if stability.hac_pvalue > policy.max_hac_pvalue:
            reasons.append("ENSEMBLE_HAC_NOT_SIGNIFICANT")
        if stability.bootstrap_pvalue > policy.max_bootstrap_pvalue:
            reasons.append("ENSEMBLE_BLOCK_BOOTSTRAP_NOT_SIGNIFICANT")
        passed = not reasons
        reasons.append("A_SHARE_EXECUTION_NOT_CERTIFIED")
        return AshareResearchOutcome(
            status=("ENSEMBLE_VALIDATION_PASSED_UNCONFIRMED" if passed else "ENSEMBLE_VALIDATION_FAILED"),
            ensemble_validation_passed=passed,
            promotion_eligible=False,
            reason_codes=tuple(reasons),
            policy=policy,
        )

'''
text, count = re.subn(
    r"    @staticmethod\n    def _comparison\([\s\S]*?(?=    def run\()",
    comparison_methods,
    text,
)
if count != 1:
    raise RuntimeError(f"acceptance comparison method replacement: expected one match, found {count}")
text = replace_once(
    text,
    "        frozen = AshareFrozenFactorEnsemble.from_development(\n"
    "            development_report,\n"
    "            selection,\n"
    "        )\n"
    "        validation_report = self.validation_analyzer.analyze(\n",
    "        frozen = AshareFrozenFactorEnsemble.from_development(\n"
    "            development_report,\n"
    "            selection,\n"
    "        )\n"
    "        development_stability = self.development_stability_analyzer.analyze(\n"
    "            artifacts, request=development_request\n"
    "        )\n"
    "        validation_report = self.validation_analyzer.analyze(\n",
    "acceptance development stability",
)
text = replace_once(
    text,
    "        panel = self._ensemble_panel(artifacts, frozen, validation_request)\n"
    "        ensemble = self._ensemble_report(panel, frozen)\n"
    "        comparison = self._comparison(validation_report, ensemble)\n",
    "        validation_stability = self.validation_stability_analyzer.analyze(\n"
    "            artifacts, request=validation_request\n"
    "        )\n"
    "        panel = self._ensemble_panel(artifacts, frozen, validation_request)\n"
    "        ensemble = self._ensemble_report(panel, frozen)\n"
    "        ensemble_stability = self.validation_stability_analyzer.analyze_panel(\n"
    "            feature_id=ensemble.feature_id,\n"
    "            feature_digest=ensemble.feature_digest,\n"
    "            panel=panel,\n"
    "        )\n"
    "        comparison = self._comparison(development_report, validation_report, ensemble)\n"
    "        research_outcome = self._research_outcome(ensemble, ensemble_stability)\n",
    "acceptance validation stability",
)
text = replace_once(
    text,
    "            validation_comparison=comparison,\n"
    "            reserve_start=reserve_start,\n",
    "            validation_comparison=comparison,\n"
    "            development_stability=development_stability,\n"
    "            validation_stability=validation_stability,\n"
    "            validation_ensemble_stability=ensemble_stability,\n"
    "            research_outcome=research_outcome,\n"
    "            reserve_start=reserve_start,\n",
    "acceptance result stability arguments",
)
path.write_text(text, encoding="utf-8")

path = root / "docs/development/roadmap.md"
text = path.read_text(encoding="utf-8")
text = text.replace(
    "### P0 — A2 real-data acceptance\n\n"
    "1. Run the deterministic 100–200 stock A2 baseline on the frozen local dataset.\n"
    "2. Confirm exact replay and record performance/memory observations.\n"
    "3. Run at least two Agent Factor Quant discovery rounds using development-only feedback.\n"
    "4. Preserve the complete adaptive candidate denominator and validate frozen ensemble factors on 2022–2024.\n"
    "5. Keep the 2025+ reserve untouched.\n",
    "### P0 — A2.5 research correctness and stability\n\n"
    "1. Use pre-split warm-up data for rolling universe filters; split starts must not create artificial zero-eligible sessions.\n"
    "2. Keep system completion separate from the research verdict and report validation comparisons with development-frozen direction.\n"
    "3. Report rolling/yearly RankIC stability, sign consistency, quantile monotonicity, coverage and turnover stability.\n"
    "4. Use HAC and deterministic block-bootstrap inference, with Holm and BH adjustments over the complete candidate family.\n"
    "5. Keep the 2025+ reserve untouched and do not promote A-share factors before A3 execution semantics.\n",
)
path.write_text(text, encoding="utf-8")

path = root / "docs/development/changelog.md"
text = path.read_text(encoding="utf-8")
marker = "This file summarizes meaningful development milestones. Commit and pull-request history remains the detailed audit trail.\n"
entry = """

## 2026-08-27 — A2.5 research correctness and stability

- added split-independent liquidity warm-up to remove artificial zero-eligible split starts;
- separated workflow completion from the factor research verdict;
- changed validation comparisons to development-frozen direction and signed deltas;
- added rolling/yearly RankIC stability, HAC inference, deterministic block bootstrap and family-wise Holm/BH adjustments;
- kept the A-share ensemble ineligible for promotion until execution semantics are certified.
"""
if entry.strip() not in text:
    text = text.replace(marker, marker + entry, 1)
path.write_text(text, encoding="utf-8")
