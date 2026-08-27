from __future__ import annotations

from dataclasses import replace

from .ashare_supplemental import AshareSupplementalDataStore
from .local_ashare import LocalAshareSecurityMaster


class SupplementedAshareSecurityMaster(LocalAshareSecurityMaster):
    """Overlay explicitly sourced supplemental records onto a vendor security master.

    The overlay currently fills delisting dates only. It never rewrites the vendor
    Parquet and never upgrades the source to survivorship-certified while the
    supplemental dataset declares partial coverage.
    """

    def __init__(
        self,
        base: LocalAshareSecurityMaster,
        supplement: AshareSupplementalDataStore,
    ) -> None:
        records = []
        applied = 0
        for record in base.records:
            extra = supplement.delisting(record.ts_code)
            if extra is None:
                records.append(record)
                continue
            if record.delist_date is not None and record.delist_date != extra.effective_date:
                raise ValueError(
                    f"vendor/supplement delisting conflict for {record.ts_code}: "
                    f"{record.delist_date} vs {extra.effective_date}"
                )
            if record.delist_date is None:
                record = replace(record, delist_date=extra.effective_date)
                applied += 1
            records.append(record)
        limitations = list(base.limitations)
        limitations.append(
            f"supplemental reference data {supplement.data_version} has "
            f"coverage={supplement.coverage!r}; {applied} delisting dates applied"
        )
        super().__init__(
            records,
            data_version=f"{base.data_version}+{supplement.data_version}",
            source_path=base.source_path,
            limitations=limitations,
        )
        self.supplement = supplement
        self.applied_delistings = applied

    @property
    def survivorship_certified(self) -> bool:
        # Presence of hand-collected/partial supplements is not evidence of complete
        # historical coverage. A future certified master needs an explicit coverage
        # contract rather than a heuristic based on record count.
        return False
