from __future__ import annotations

import base64
import gzip
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAYLOAD_DIR = ROOT / "tools/workspace_payload"

encoded = "".join(
    path.read_text(encoding="utf-8").strip()
    for path in sorted(PAYLOAD_DIR.glob("*.txt"))
)
if not encoded:
    raise RuntimeError("Workspace V1 payload is empty")
source = gzip.decompress(base64.b64decode(encoded)).decode("utf-8")
exec(compile(source, "<workspace-v1-apply>", "exec"))
