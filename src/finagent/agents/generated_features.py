from __future__ import annotations

import ast
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from finagent.domain._validation import require_aware_datetime, require_non_empty
from finagent.domain.experiments import ArtifactRef, ArtifactType


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    feature_id: str
    name: str
    description: str
    hypothesis: str
    input_fields: tuple[str, ...]
    lookback: int

    def __post_init__(self) -> None:
        for name in ("feature_id", "name", "description", "hypothesis"):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", self.feature_id):
            raise ValueError("feature_id contains unsupported characters")
        fields = tuple(require_non_empty(value, "input field") for value in self.input_fields)
        if not fields or len(set(fields)) != len(fields):
            raise ValueError("input_fields must be non-empty and unique")
        object.__setattr__(self, "input_fields", fields)
        if isinstance(self.lookback, bool) or not isinstance(self.lookback, int) or self.lookback < 1:
            raise ValueError("lookback must be an integer >= 1")


@dataclass(frozen=True, slots=True)
class FeatureCodePolicy:
    function_name: str = "compute_feature"
    max_source_chars: int = 12000
    max_ast_nodes: int = 600
    max_comprehensions: int = 8
    allowed_builtin_calls: tuple[str, ...] = (
        "abs", "all", "any", "enumerate", "float", "int", "len", "max", "min", "range", "round", "sum", "zip"
    )
    allowed_math_members: tuple[str, ...] = (
        "acos", "asin", "atan", "ceil", "cos", "e", "exp", "fabs", "floor", "log", "log10", "pi", "pow", "sin", "sqrt", "tan"
    )

    def __post_init__(self) -> None:
        if self.max_source_chars < 256 or self.max_ast_nodes < 32 or self.max_comprehensions < 0:
            raise ValueError("invalid feature code policy limits")


@dataclass(frozen=True, slots=True)
class FeatureValidationReport:
    validator_version: str
    node_count: int
    comprehension_count: int
    source_digest: str


class FeatureCodeValidationError(ValueError):
    pass


class FeatureCodeValidator:
    VERSION = "feature-ast-v1"

    _FORBIDDEN_NODES = (
        ast.Import, ast.ImportFrom, ast.ClassDef, ast.AsyncFunctionDef, ast.Lambda,
        ast.Global, ast.Nonlocal, ast.With, ast.AsyncWith, ast.Try, ast.Raise,
        ast.While, ast.Delete, ast.Yield, ast.YieldFrom, ast.Await,
    )
    _FORBIDDEN_CALLS = {
        "breakpoint", "compile", "delattr", "dir", "eval", "exec", "getattr",
        "globals", "help", "input", "locals", "memoryview", "open", "setattr",
        "super", "type", "vars", "__import__",
    }

    def __init__(self, policy: FeatureCodePolicy = FeatureCodePolicy()) -> None:
        self.policy = policy

    def validate(self, source: str) -> FeatureValidationReport:
        source = require_non_empty(source, "source")
        if len(source) > self.policy.max_source_chars:
            raise FeatureCodeValidationError("generated feature source exceeds max_source_chars")
        try:
            tree = ast.parse(source, mode="exec")
        except SyntaxError as exc:
            raise FeatureCodeValidationError(f"generated feature source is invalid Python: {exc}") from exc

        body = list(tree.body)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            body = body[1:]
        if len(body) != 1 or not isinstance(body[0], ast.FunctionDef):
            raise FeatureCodeValidationError("source must contain exactly one top-level function")
        fn = body[0]
        if fn.name != self.policy.function_name:
            raise FeatureCodeValidationError(f"top-level function must be {self.policy.function_name!r}")
        if fn.decorator_list or fn.returns is not None:
            raise FeatureCodeValidationError("feature function decorators/return annotations are not allowed")
        args = fn.args
        if len(args.args) != 1 or args.args[0].arg != "inputs" or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg:
            raise FeatureCodeValidationError("feature function signature must be compute_feature(inputs)")
        if args.defaults or args.kw_defaults:
            raise FeatureCodeValidationError("feature function defaults are not allowed")

        nodes = tuple(ast.walk(tree))
        if len(nodes) > self.policy.max_ast_nodes:
            raise FeatureCodeValidationError("generated feature AST exceeds max_ast_nodes")
        comprehension_count = sum(isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)) for n in nodes)
        if comprehension_count > self.policy.max_comprehensions:
            raise FeatureCodeValidationError("generated feature uses too many comprehensions")

        for node in nodes:
            if isinstance(node, self._FORBIDDEN_NODES):
                raise FeatureCodeValidationError(f"forbidden syntax: {type(node).__name__}")
            if isinstance(node, ast.Name) and node.id.startswith("__"):
                raise FeatureCodeValidationError("dunder names are forbidden")
            if isinstance(node, ast.Attribute):
                if not isinstance(node.value, ast.Name) or node.value.id != "math" or node.attr not in self.policy.allowed_math_members:
                    raise FeatureCodeValidationError("attribute access is restricted to approved math members")
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in self._FORBIDDEN_CALLS or node.func.id not in self.policy.allowed_builtin_calls:
                        raise FeatureCodeValidationError(f"call to {node.func.id!r} is not allowed")
                elif isinstance(node.func, ast.Attribute):
                    # Attribute validity is checked above.
                    pass
                else:
                    raise FeatureCodeValidationError("indirect/dynamic calls are not allowed")

        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        return FeatureValidationReport(self.VERSION, len(nodes), comprehension_count, digest)


@dataclass(frozen=True, slots=True)
class GeneratedFeatureArtifact:
    spec: FeatureSpec
    source: str
    validation: FeatureValidationReport
    generated_at: datetime
    generator_id: str
    smoke_output_digest: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", require_non_empty(self.source, "source"))
        object.__setattr__(self, "generated_at", require_aware_datetime(self.generated_at, "generated_at"))
        object.__setattr__(self, "generator_id", require_non_empty(self.generator_id, "generator_id"))
        object.__setattr__(self, "smoke_output_digest", require_non_empty(self.smoke_output_digest, "smoke_output_digest"))
        if hashlib.sha256(self.source.encode("utf-8")).hexdigest() != self.validation.source_digest:
            raise ValueError("source digest does not match validation report")
        object.__setattr__(self, "metadata", MappingProxyType({str(k): str(v) for k, v in self.metadata.items()}))

    @property
    def digest(self) -> str:
        payload = {
            "spec": {
                "feature_id": self.spec.feature_id,
                "name": self.spec.name,
                "description": self.spec.description,
                "hypothesis": self.spec.hypothesis,
                "input_fields": list(self.spec.input_fields),
                "lookback": self.spec.lookback,
            },
            "source_digest": self.validation.source_digest,
            "validator_version": self.validation.validator_version,
            "smoke_output_digest": self.smoke_output_digest,
            "generator_id": self.generator_id,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

    def code_artifact_ref(self) -> ArtifactRef:
        return ArtifactRef(
            artifact_id=f"feature-code:{self.spec.feature_id}",
            artifact_type=ArtifactType.CODE,
            version="phase3d-v1",
            digest=self.digest,
            uri=f"generated-feature://{self.spec.feature_id}/{self.digest}",
        )

    def factor_artifact_ref(self) -> ArtifactRef:
        return ArtifactRef(
            artifact_id=f"feature:{self.spec.feature_id}",
            artifact_type=ArtifactType.FACTOR,
            version="phase3d-v1",
            digest=self.digest,
            uri=f"generated-feature://{self.spec.feature_id}/{self.digest}",
        )


class SQLiteGeneratedFeatureStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS generated_features (
                    digest TEXT PRIMARY KEY,
                    feature_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    generated_at TEXT NOT NULL
                )
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_generated_features_id ON generated_features(feature_id)")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    @staticmethod
    def _payload(artifact: GeneratedFeatureArtifact) -> dict[str, object]:
        return {
            "spec": {
                "feature_id": artifact.spec.feature_id,
                "name": artifact.spec.name,
                "description": artifact.spec.description,
                "hypothesis": artifact.spec.hypothesis,
                "input_fields": list(artifact.spec.input_fields),
                "lookback": artifact.spec.lookback,
            },
            "validation": {
                "validator_version": artifact.validation.validator_version,
                "node_count": artifact.validation.node_count,
                "comprehension_count": artifact.validation.comprehension_count,
                "source_digest": artifact.validation.source_digest,
            },
            "generator_id": artifact.generator_id,
            "smoke_output_digest": artifact.smoke_output_digest,
            "metadata": dict(artifact.metadata),
        }

    def register(self, artifact: GeneratedFeatureArtifact) -> None:
        payload = self._payload(artifact)
        with self._connect() as con:
            try:
                con.execute(
                    "INSERT INTO generated_features VALUES (?, ?, ?, ?, ?)",
                    (artifact.digest, artifact.spec.feature_id, artifact.source, json.dumps(payload, sort_keys=True, ensure_ascii=False), artifact.generated_at.isoformat()),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"generated feature digest {artifact.digest!r} is already registered") from exc

    def get(self, digest: str) -> GeneratedFeatureArtifact:
        with self._connect() as con:
            row = con.execute("SELECT source, payload_json, generated_at FROM generated_features WHERE digest=?", (digest,)).fetchone()
        if row is None:
            raise KeyError(digest)
        payload = json.loads(row[1])
        spec_payload = payload["spec"]
        validation_payload = payload["validation"]
        return GeneratedFeatureArtifact(
            spec=FeatureSpec(
                feature_id=spec_payload["feature_id"], name=spec_payload["name"], description=spec_payload["description"],
                hypothesis=spec_payload["hypothesis"], input_fields=tuple(spec_payload["input_fields"]), lookback=int(spec_payload["lookback"]),
            ),
            source=row[0],
            validation=FeatureValidationReport(
                validation_payload["validator_version"], int(validation_payload["node_count"]),
                int(validation_payload["comprehension_count"]), validation_payload["source_digest"],
            ),
            generated_at=datetime.fromisoformat(row[2]),
            generator_id=payload["generator_id"],
            smoke_output_digest=payload["smoke_output_digest"],
            metadata=payload.get("metadata", {}),
        )

    def digests_for_feature(self, feature_id: str) -> tuple[str, ...]:
        with self._connect() as con:
            rows = con.execute("SELECT digest FROM generated_features WHERE feature_id=? ORDER BY generated_at, digest", (feature_id,)).fetchall()
        return tuple(row[0] for row in rows)
