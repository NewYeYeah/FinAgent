from pathlib import Path

path = Path(__file__).resolve().parents[1] / "src" / "finagent" / "realtime" / "sources.py"
text = path.read_text(encoding="utf-8")
old = "import hashlib\nimport json\nimport math\nfrom dataclasses import dataclass\nfrom datetime import UTC, datetime\nfrom collections.abc import AsyncIterator\nfrom enum import StrEnum\n"
new = "import hashlib\nimport json\nimport math\nfrom collections.abc import AsyncIterator\nfrom dataclasses import dataclass\nfrom datetime import UTC, datetime\nfrom enum import StrEnum\n"
if text.count(old) != 1:
    raise RuntimeError("unexpected sources.py import block")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("fixed sources.py import ordering")
