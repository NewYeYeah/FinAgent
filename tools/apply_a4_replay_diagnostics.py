from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"missing replay diagnostic anchor: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    path = "scripts/run_ashare_portfolio_validation.py"
    replace_once(
        path,
        '''def _write_ledger(path: Path, rows: tuple[dict[str, object], ...]) -> None:\n    path.parent.mkdir(parents=True, exist_ok=True)\n    with path.open("w", encoding="utf-8") as handle:\n        for row in rows:\n            handle.write(\n                json.dumps(\n                    row,\n                    sort_keys=True,\n                    separators=(",", ":"),\n                    ensure_ascii=False,\n                    allow_nan=False,\n                )\n                + "\\n"\n            )\n\n\n''',
        '''def _write_ledger(path: Path, rows: tuple[dict[str, object], ...]) -> None:\n    path.parent.mkdir(parents=True, exist_ok=True)\n    with path.open("w", encoding="utf-8") as handle:\n        for row in rows:\n            handle.write(\n                json.dumps(\n                    row,\n                    sort_keys=True,\n                    separators=(",", ":"),\n                    ensure_ascii=False,\n                    allow_nan=False,\n                )\n                + "\\n"\n            )\n\n\ndef _first_difference(expected: object, actual: object, path: str = "$") -> str:\n    if type(expected) is not type(actual):\n        return f"{path}: type {type(expected).__name__} != {type(actual).__name__}"\n    if isinstance(expected, Mapping):\n        expected_keys = set(expected)\n        actual_keys = set(actual)\n        if expected_keys != actual_keys:\n            return (\n                f"{path}: keys missing={sorted(expected_keys - actual_keys)} "\n                f"extra={sorted(actual_keys - expected_keys)}"\n            )\n        for key in sorted(expected_keys):\n            difference = _first_difference(\n                expected[key],\n                actual[key],\n                f"{path}.{key}",\n            )\n            if difference:\n                return difference\n        return ""\n    if isinstance(expected, list):\n        if len(expected) != len(actual):\n            return f"{path}: length {len(expected)} != {len(actual)}"\n        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):\n            difference = _first_difference(left, right, f"{path}[{index}]")\n            if difference:\n                return difference\n        return ""\n    if expected != actual:\n        return f"{path}: {expected!r} != {actual!r}"\n    return ""\n\n\n''',
    )
    replace_once(
        path,
        '''    if args.assert_replay:\n        assert reference is not None\n        expected_id = str(reference.get("portfolio_validation_id", ""))\n        expected_ledger = str(reference.get("ledger_digest", ""))\n        if result.result_id != expected_id or result.ledger_digest != expected_ledger:\n            raise RuntimeError(\n                "A4 exact replay failed: result or execution-ledger identity differs"\n            )\n\n    result.write_json(report_path)\n    _write_ledger(ledger_path, ledger_rows)\n''',
        '''    result.write_json(report_path)\n    _write_ledger(ledger_path, ledger_rows)\n\n    if args.assert_replay:\n        assert reference is not None\n        expected_id = str(reference.get("portfolio_validation_id", ""))\n        expected_ledger = str(reference.get("ledger_digest", ""))\n        if result.result_id != expected_id or result.ledger_digest != expected_ledger:\n            expected_body = dict(reference)\n            actual_body = result.to_dict()\n            for payload in (expected_body, actual_body):\n                payload.pop("mode", None)\n                payload.pop("portfolio_validation_id", None)\n            difference = _first_difference(expected_body, actual_body)\n            raise RuntimeError(\n                "A4 exact replay failed: "\n                f"result {result.result_id} != {expected_id}; "\n                f"ledger {result.ledger_digest} != {expected_ledger}; "\n                f"first_difference={difference or 'none'}"\n            )\n\n''',
    )


if __name__ == "__main__":
    main()
