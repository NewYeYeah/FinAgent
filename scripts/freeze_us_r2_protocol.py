from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path

from finagent.research.us_r2_frozen_protocol import freeze_us_r2_protocol_from_inventory


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _load_json(path: Path) -> Mapping[str, object]:
    payload: object = json.loads(path.read_text(encoding="utf-8"))
    return _mapping(payload, str(path))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate the reviewed US-R2 corpus inventory and materialize the frozen row-free "
            "dynamic-cross-section/regime protocol. No factor result is read or computed."
        )
    )
    parser.add_argument(
        "--inventory",
        type=Path,
        default=Path("reports/us_r2/us_r2_regime_corpus_inventory.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/us_r2/us_r2_frozen_protocol.json"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    inventory = _load_json(args.inventory)
    frozen = freeze_us_r2_protocol_from_inventory(inventory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(frozen.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    console = {
        "freeze_id": frozen.freeze_id,
        "inventory_corpus_id": frozen.inventory_corpus_id,
        "cross_section_policy_id": frozen.cross_section_policy.policy_id,
        "regime_policy_id": frozen.regime_policy.policy_id,
        "classifier_id": frozen.classifier_policy.classifier_id,
        "walk_forward_protocol_id": frozen.walk_forward_protocol.protocol_id,
        "fold_count": len(frozen.walk_forward_protocol.folds),
        "allowed_asset_count": len(frozen.cross_section_policy.allowed_assets),
        "minimum_cross_section": frozen.cross_section_policy.minimum_cross_section,
        "static_all_asset_intersection_rejected": frozen.static_all_asset_intersection_rejected,
        "output": str(args.output),
    }
    print(json.dumps(console, sort_keys=True, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
