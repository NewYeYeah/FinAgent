from pathlib import Path

path = Path("docs/development/changelog.md")
text = path.read_text(encoding="utf-8")
old = "replay-experiment-campaign-35b80d37b1c36bd08c9eb6f1"
new = "replay-experiment-campaign-ae3eadfdd7110176150e9a99"
if text.count(old) != 1:
    raise SystemExit(f"expected exactly one stale replay campaign identity, found {text.count(old)}")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
