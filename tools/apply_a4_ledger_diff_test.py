from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"missing ledger diff anchor: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    path = "tests/test_ashare_portfolio_validation_a4.py"
    replace_once(
        path,
        '''ROOT = Path(__file__).resolve().parents[1]\n\n\ndef _range''',
        '''ROOT = Path(__file__).resolve().parents[1]\n\n\ndef _json_difference(expected: object, actual: object, path: str = "$") -> str:\n    if type(expected) is not type(actual):\n        return f"{path}: type {type(expected).__name__} != {type(actual).__name__}"\n    if isinstance(expected, dict):\n        keys = set(expected) | set(actual)\n        for key in sorted(keys):\n            if key not in expected or key not in actual:\n                return f"{path}.{key}: key presence differs"\n            difference = _json_difference(expected[key], actual[key], f"{path}.{key}")\n            if difference:\n                return difference\n        return ""\n    if isinstance(expected, list):\n        if len(expected) != len(actual):\n            return f"{path}: length {len(expected)} != {len(actual)}"\n        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):\n            difference = _json_difference(left, right, f"{path}[{index}]")\n            if difference:\n                return difference\n        return ""\n    if expected != actual:\n        return f"{path}: {expected!r} != {actual!r}"\n    return ""\n\n\ndef _ledger_difference(expected_path: Path, actual_path: Path) -> str:\n    expected_lines = expected_path.read_text(encoding="utf-8").splitlines()\n    actual_lines = actual_path.read_text(encoding="utf-8").splitlines()\n    if len(expected_lines) != len(actual_lines):\n        return f"ledger length {len(expected_lines)} != {len(actual_lines)}"\n    for index, (left, right) in enumerate(zip(expected_lines, actual_lines, strict=True)):\n        if left != right:\n            return f"line {index}: " + _json_difference(json.loads(left), json.loads(right))\n    return "no JSONL field difference found"\n\n\ndef _range''',
    )
    replace_once(
        path,
        '''    assert second.returncode == 0, second.stderr + second.stdout\n    replay_payload = json.loads(replay.read_text(encoding="utf-8"))\n''',
        '''    assert second.returncode == 0, (\n        second.stderr\n        + second.stdout\n        + "\\nledger_difference="\n        + (\n            _ledger_difference(ledger, replay_ledger)\n            if replay_ledger.exists()\n            else "replay ledger was not written"\n        )\n    )\n    replay_payload = json.loads(replay.read_text(encoding="utf-8"))\n''',
    )


if __name__ == "__main__":
    main()
