from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
from scipy.stats import chi2

from finagent.domain.assets import AssetId
from finagent.domain.research import ResearchDataset


@dataclass(frozen=True, slots=True)
class RandomWalkAssetStats:
    observations: int
    mean: float
    std: float
    autocorrelation: tuple[float, ...]
    ljung_box_q: float
    ljung_box_pvalue: float


@dataclass(frozen=True, slots=True)
class RandomWalkReport:
    split: str
    return_feature: str
    lags: int
    assets: Mapping[AssetId, RandomWalkAssetStats]


class RandomWalkDiagnostics:
    def __init__(self, return_feature: str = "log_return_1", lags: int = 10) -> None:
        if lags <= 0:
            raise ValueError("lags must be >= 1")
        self.return_feature = return_feature
        self.lags = int(lags)

    @staticmethod
    def _acf(series: np.ndarray, max_lag: int) -> tuple[float, ...]:
        centered = series - np.mean(series)
        denom = float(np.dot(centered, centered))
        if denom <= 0:
            return tuple(0.0 for _ in range(max_lag))
        return tuple(
            float(np.dot(centered[lag:], centered[:-lag]) / denom)
            for lag in range(1, max_lag + 1)
        )

    def run(self, dataset: ResearchDataset, split: str = "train") -> RandomWalkReport:
        panel = dataset.get_split(split)
        returns = panel.feature_panel(self.return_feature)
        results: dict[AssetId, RandomWalkAssetStats] = {}
        for idx, asset in enumerate(panel.assets):
            series = returns[:, idx]
            series = series[np.isfinite(series)]
            if len(series) < 3:
                raise ValueError(f"insufficient returns for diagnostics on {asset.key}")
            effective_lags = min(self.lags, len(series) - 1)
            acf = self._acf(series, effective_lags)
            n = len(series)
            q = n * (n + 2.0) * sum(
                (rho * rho) / (n - lag)
                for lag, rho in enumerate(acf, start=1)
            )
            pvalue = float(chi2.sf(q, df=effective_lags))
            results[asset] = RandomWalkAssetStats(
                observations=n,
                mean=float(np.mean(series)),
                std=float(np.std(series, ddof=1)),
                autocorrelation=acf,
                ljung_box_q=float(q),
                ljung_box_pvalue=pvalue,
            )
        return RandomWalkReport(
            split=split,
            return_feature=self.return_feature,
            lags=self.lags,
            assets=results,
        )
