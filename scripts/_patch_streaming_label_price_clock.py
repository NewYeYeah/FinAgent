from pathlib import Path

path = Path("src/finagent/research/streaming_experiment_bridge.py")
text = path.read_text(encoding="utf-8")

replacements = (
    (
        "    label_available: bool\n    target_event_time: datetime | None = None\n",
        "    label_available: bool\n    price_event_time: datetime | None = None\n    target_event_time: datetime | None = None\n",
    ),
    (
        "        object.__setattr__(\n            self,\n            \"source_available_at\",\n            _aware(self.source_available_at, \"source_available_at\"),\n        )\n        source_price = _number(self.source_price, \"source_price\")\n",
        "        object.__setattr__(\n            self,\n            \"source_available_at\",\n            _aware(self.source_available_at, \"source_available_at\"),\n        )\n        price_event_time = _optional_aware(self.price_event_time, \"price_event_time\")\n        if price_event_time is not None:\n            if price_event_time >= self.source_available_at:\n                raise ValueError(\"price_event_time must precede source_available_at\")\n            if abs((self.source_available_at - price_event_time).total_seconds() - 60.0) > 1e-9:\n                raise ValueError(\"price_event_time must be the source 1m close event for source_available_at\")\n        object.__setattr__(self, \"price_event_time\", price_event_time)\n        source_price = _number(self.source_price, \"source_price\")\n",
    ),
    (
        "        if include_id:\n            payload[\"label_id\"] = self.label_id\n        return payload\n\n\n@dataclass(frozen=True, slots=True)\nclass StreamingResearchEvidenceBundle:",
        "        if self.price_event_time is not None:\n            payload[\"price_event_time\"] = self.price_event_time.isoformat()\n        if include_id:\n            payload[\"label_id\"] = self.label_id\n        return payload\n\n\n@dataclass(frozen=True, slots=True)\nclass StreamingResearchEvidenceBundle:",
    ),
    (
        "        target_event_time=_optional_aware(\n            document.get(\"target_event_time\"),\n            \"label.target_event_time\",\n        ),\n",
        "        price_event_time=_optional_aware(\n            document.get(\"price_event_time\"),\n            \"label.price_event_time\",\n        ),\n        target_event_time=_optional_aware(\n            document.get(\"target_event_time\"),\n            \"label.target_event_time\",\n        ),\n",
    ),
    (
        '            "source_event_time": label.source_event_time if label is not None else None,\n',
        '            "source_event_time": (\n                (label.price_event_time or label.source_event_time)\n                if label is not None\n                else None\n            ),\n',
    ),
)

for old, new in replacements:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one replacement target, found {count}: {old[:80]!r}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
