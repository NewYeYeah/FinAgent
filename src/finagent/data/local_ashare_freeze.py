from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from .local_ashare import AshareBarFrequency, LocalAshareDatasetLayout


def _sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class FrozenLocalFile:
    relative_path: str
    size: int
    mtime_ns: int
    sha256: str = ""

    def __post_init__(self) -> None:
        if not self.relative_path.strip() or self.size < 0 or self.mtime_ns < 0:
            raise ValueError("invalid frozen local file metadata")
        if self.sha256 and len(self.sha256) != 64:
            raise ValueError("sha256 must be empty or a 64-character digest")

    def to_dict(self) -> dict[str, object]:
        return {
            "relative_path": self.relative_path,
            "size": self.size,
            "mtime_ns": self.mtime_ns,
            "sha256": self.sha256 or None,
        }


@dataclass(frozen=True, slots=True)
class LocalAshareFrozenManifest:
    files: tuple[FrozenLocalFile, ...]
    frequencies: tuple[str, ...]
    created_at: datetime
    content_hashed: bool
    schema_version: str = "finagent.local-ashare-frozen-manifest.v1"

    def __post_init__(self) -> None:
        if not self.files:
            raise ValueError("frozen local A-share manifest cannot be empty")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        paths = [item.relative_path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("frozen manifest contains duplicate paths")
        if self.content_hashed and any(not item.sha256 for item in self.files):
            raise ValueError("content_hashed manifest requires every file SHA-256")

    @property
    def dataset_version(self) -> str:
        if self.content_hashed:
            files = [
                {
                    "relative_path": item.relative_path,
                    "size": item.size,
                    "sha256": item.sha256,
                }
                for item in self.files
            ]
        else:
            files = [
                {
                    "relative_path": item.relative_path,
                    "size": item.size,
                    "mtime_ns": item.mtime_ns,
                }
                for item in self.files
            ]
        payload = {
            "schema_version": self.schema_version,
            "frequencies": list(self.frequencies),
            "content_hashed": self.content_hashed,
            "files": files,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return f"local-ashare-frozen-{hashlib.sha256(encoded).hexdigest()[:24]}"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "dataset_version": self.dataset_version,
            "created_at": self.created_at.astimezone(UTC).isoformat(),
            "frequencies": list(self.frequencies),
            "content_hashed": self.content_hashed,
            "files": [item.to_dict() for item in self.files],
        }

    def write_json(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(self.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return output

    @classmethod
    def read_json(cls, path: str | Path) -> LocalAshareFrozenManifest:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("schema_version") != "finagent.local-ashare-frozen-manifest.v1":
            raise ValueError("unsupported local A-share frozen manifest schema")
        files = tuple(
            FrozenLocalFile(
                relative_path=str(item["relative_path"]),
                size=int(item["size"]),
                mtime_ns=int(item["mtime_ns"]),
                sha256=str(item.get("sha256") or ""),
            )
            for item in payload["files"]
        )
        created_at = datetime.fromisoformat(str(payload["created_at"]))
        manifest = cls(
            files=files,
            frequencies=tuple(str(value) for value in payload["frequencies"]),
            created_at=created_at,
            content_hashed=bool(payload["content_hashed"]),
        )
        expected = str(payload.get("dataset_version", ""))
        if expected and manifest.dataset_version != expected:
            raise ValueError("local A-share frozen manifest dataset_version mismatch")
        return manifest

    def verify(
        self,
        layout: LocalAshareDatasetLayout,
        *,
        verify_content: bool | None = None,
    ) -> None:
        verify_content = self.content_hashed if verify_content is None else verify_content
        if verify_content and not self.content_hashed:
            raise ValueError(
                "full content verification requires a content_hashed frozen manifest; "
                "regenerate the A-share frozen manifest with content_hash=True"
            )
        for frozen in self.files:
            path = layout.root / Path(frozen.relative_path)
            if not path.is_file():
                raise FileNotFoundError(f"frozen A-share file missing: {path}")
            stat = path.stat()
            if stat.st_size != frozen.size:
                raise ValueError(f"frozen A-share file size changed: {frozen.relative_path}")
            if self.content_hashed:
                if verify_content:
                    if not frozen.sha256:
                        raise ValueError(
                            f"frozen manifest has no content hash for {frozen.relative_path}"
                        )
                    if _sha256_file(path) != frozen.sha256:
                        raise ValueError(
                            f"frozen A-share file digest changed: {frozen.relative_path}"
                        )
            elif stat.st_mtime_ns != frozen.mtime_ns:
                raise ValueError(f"frozen A-share file mtime changed: {frozen.relative_path}")


def create_local_ashare_frozen_manifest(
    layout: LocalAshareDatasetLayout,
    *,
    frequencies: Iterable[AshareBarFrequency] = (AshareBarFrequency.DAILY,),
    content_hash: bool = True,
    created_at: datetime | None = None,
) -> LocalAshareFrozenManifest:
    selected = tuple(dict.fromkeys(frequencies))
    if not selected:
        raise ValueError("at least one A-share frequency must be frozen")
    paths: list[Path] = [layout.basic_path]
    for frequency in selected:
        layout.require(frequency)
        if frequency is AshareBarFrequency.DAILY:
            paths.append(layout.daily_path)
        else:
            paths.extend(sorted(layout.intraday_directory(frequency).glob("*.parquet")))
    unique_paths = tuple(dict.fromkeys(paths))
    files: list[FrozenLocalFile] = []
    for path in unique_paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        stat = path.stat()
        files.append(
            FrozenLocalFile(
                relative_path=path.relative_to(layout.root).as_posix(),
                size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                sha256=_sha256_file(path) if content_hash else "",
            )
        )
    return LocalAshareFrozenManifest(
        files=tuple(files),
        frequencies=tuple(frequency.value for frequency in selected),
        created_at=created_at or datetime.now(UTC),
        content_hashed=content_hash,
    )
