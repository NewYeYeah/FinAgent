from pathlib import Path
path = Path("workspace/src/workbench/experiments.tsx")
text = path.read_text(encoding="utf-8")
old = "Hidden chain-of-thought is not persisted or exposed."
new = "Hidden chain-of-thought is not persisted or projected."
if old not in text:
    raise SystemExit("reasoning-boundary wording anchor missing")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
