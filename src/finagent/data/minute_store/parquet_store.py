from __future__ import annotations

from finagent.data.capabilities import AdapterCapabilities
from finagent.data.query import MarketDataField, MarketDataQuery, MarketDataView, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval

from .manifest import MinuteStoreManifest
from .query import MinuteQueryPlan, build_minute_query_plan

US_MINUTE_DUCKDB_ADAPTER_ID = "us-minute-duckdb-parquet-v1"


class DuckDBParquetMinuteStore:
    """Lazy, bounded query surface over admitted monthly minute Parquet partitions.

    US-D1 intentionally implements only source-native 1m, raw-price, all-observed
    reads. Session filtering, adjusted research prices and resampling remain explicit
    capability gaps until US-D2 freezes those semantics.
    """

    def __init__(self, manifest: MinuteStoreManifest) -> None:
        self.manifest = manifest
        self.capabilities = AdapterCapabilities(
            adapter_id=US_MINUTE_DUCKDB_ADAPTER_ID,
            provider=manifest.source_id,
            market_ids=frozenset({manifest.market_id}),
            intervals=frozenset({BarInterval.MINUTE_1}),
            fields=frozenset(MarketDataField),
            session_policies=frozenset({SessionPolicy.ALL_OBSERVED}),
            adjustment_policies=frozenset({ResearchPriceBasis.RAW}),
            availability_policies=frozenset(
                {AvailabilityPolicy.AVAILABLE_AT, AvailabilityPolicy.EVENT_TIME}
            ),
            supports_corporate_actions=False,
            lazy_query=True,
        )

    def plan(self, query: MarketDataQuery) -> MinuteQueryPlan:
        self.capabilities.require(query)
        return build_minute_query_plan(self.manifest, query)

    def view(self, query: MarketDataQuery) -> MarketDataView:
        self.capabilities.require(query)
        return MarketDataView(
            query=query,
            adapter_id=self.capabilities.adapter_id,
            data_version=self.manifest.data_version,
            lazy=True,
            estimated_rows=None,
        )
