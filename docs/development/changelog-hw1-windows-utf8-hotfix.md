# HW-1.0-RS Windows subprocess UTF-8 hotfix

Observed on Windows/PowerShell during the real frozen Workbench smoke:

```text
UnicodeDecodeError: 'gbk' codec can't decode byte ...
TypeError: unsupported operand type(s) for +: 'NoneType' and 'str'
```

Root cause: Python `subprocess.run(..., text=True, capture_output=True)` used the host preferred Windows text encoding (GBK/cp936), while npm/npx/Playwright emitted UTF-8 diagnostic output. A subprocess reader thread could therefore fail before stdout/stderr were populated, causing a secondary `NoneType` concatenation failure.

Fix:

- all npm/npx/Playwright calls in `run_historical_workbench_release_smoke.py` now use explicit `encoding="utf-8"` and `errors="replace"`;
- captured-output formatting tolerates an unexpected `None` stream defensively;
- the subprocess exit code remains authoritative; replacement decoding affects diagnostic text only;
- regression tests emit non-ASCII UTF-8 bytes directly and verify stable capture independently of the host locale.

This hotfix changes only the HW-1.0-RS test orchestrator and its tests. It does not modify the frozen Workbench product, A2.6/A4 evidence, reserve state, PAPER authority or broker/live-capital authority.
