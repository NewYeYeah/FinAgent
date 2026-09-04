from __future__ import annotations

import os
import subprocess
import sys

_TURNOVER_PROBE = r"""
from finagent.research.us_baseline_evaluation import _turnover

current = {"asset-big": 1.0e16}
current.update({f"asset-{index:04d}": 1.0 for index in range(1000)})
one_way, gross = _turnover({}, current)
print(f"{one_way.hex()}|{gross.hex()}")
"""


def test_turnover_is_bitwise_stable_across_python_hash_seeds() -> None:
    outputs: set[str] = set()
    for seed in ("1", "2", "3", "11", "29"):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", _TURNOVER_PROBE],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        outputs.add(completed.stdout.strip())

    assert len(outputs) == 1
