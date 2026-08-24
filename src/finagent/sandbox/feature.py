from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Sequence

from finagent.domain._validation import require_non_empty
from finagent.agents.generated_features import FeatureSpec, FeatureCodeValidator

Number = int | float


@dataclass(frozen=True, slots=True)
class FeatureSandboxLimits:
    wall_time_seconds: float = 3.0
    cpu_time_seconds: int = 2
    memory_mb: int = 512
    max_output_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        if self.wall_time_seconds <= 0 or self.cpu_time_seconds < 1 or self.memory_mb < 64 or self.max_output_bytes < 1024:
            raise ValueError("invalid sandbox resource limits")


@dataclass(frozen=True, slots=True)
class FeatureSandboxRequest:
    spec: FeatureSpec
    source: str
    inputs: Mapping[str, Sequence[Number | None]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", require_non_empty(self.source, "source"))
        normalized: dict[str, tuple[float | None, ...]] = {}
        if set(self.inputs) != set(self.spec.input_fields):
            raise ValueError("sandbox inputs must exactly match FeatureSpec.input_fields")
        length: int | None = None
        for name in self.spec.input_fields:
            raw = self.inputs[name]
            values: list[float | None] = []
            for value in raw:
                if value is None:
                    values.append(None)
                    continue
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise TypeError("sandbox input values must be numeric or None")
                number = float(value)
                if not math.isfinite(number):
                    raise ValueError("sandbox input values must be finite")
                values.append(number)
            if length is None:
                length = len(values)
            elif len(values) != length:
                raise ValueError("all sandbox input fields must have equal length")
            normalized[name] = tuple(values)
        if length is None or length < self.spec.lookback:
            raise ValueError("sandbox input length must be >= feature lookback")
        object.__setattr__(self, "inputs", MappingProxyType(normalized))


@dataclass(frozen=True, slots=True)
class FeatureSandboxResult:
    values: tuple[float | None, ...]
    stdout: str = ""
    stderr: str = ""

    @property
    def output_digest(self) -> str:
        encoded = json.dumps(self.values, separators=(",", ":"), allow_nan=False).encode()
        return hashlib.sha256(encoded).hexdigest()


class FeatureSandboxError(RuntimeError):
    pass


_WRAPPER = r'''
import json, math, sys
payload = json.loads(sys.stdin.read())
source = payload["source"]
inputs = payload["inputs"]
safe_builtins = {
    "abs": abs, "all": all, "any": any, "enumerate": enumerate,
    "float": float, "int": int, "len": len, "max": max, "min": min,
    "range": range, "round": round, "sum": sum, "zip": zip,
}
globals_dict = {"__builtins__": safe_builtins, "math": math}
locals_dict = {}
exec(compile(source, "<generated-feature>", "exec"), globals_dict, locals_dict)
fn = locals_dict.get("compute_feature")
if fn is None:
    raise RuntimeError("compute_feature not found")
values = fn(inputs)
if not isinstance(values, (list, tuple)):
    raise TypeError("feature output must be list or tuple")
normalized = []
for value in values:
    if value is None:
        normalized.append(None)
    else:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("feature outputs must be numeric or None")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("feature outputs must be finite or None")
        normalized.append(number)
print(json.dumps({"values": normalized}, separators=(",", ":"), allow_nan=False))
'''


def _resource_limiter(limits: FeatureSandboxLimits):
    if os.name != "posix":
        return None
    try:
        import resource
    except ImportError:
        return None

    def apply() -> None:
        memory = limits.memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_time_seconds, limits.cpu_time_seconds))
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        resource.setrlimit(resource.RLIMIT_FSIZE, (limits.max_output_bytes, limits.max_output_bytes))
        resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        except (ValueError, OSError):
            pass
    return apply


class LocalFeatureSandbox:
    """Restricted subprocess for generated feature smoke tests.

    Security is defense-in-depth: static AST validation removes imports, dynamic calls and
    arbitrary attribute access; the subprocess receives a reduced builtin set and POSIX
    resource limits. This is not a kernel/container sandbox and must not be described as one.
    """

    def __init__(self, *, validator: FeatureCodeValidator | None = None, limits: FeatureSandboxLimits = FeatureSandboxLimits()) -> None:
        self.validator = validator or FeatureCodeValidator()
        self.limits = limits

    def run(self, request: FeatureSandboxRequest) -> FeatureSandboxResult:
        self.validator.validate(request.source)
        payload = json.dumps({"source": request.source, "inputs": {k: list(v) for k, v in request.inputs.items()}}, allow_nan=False)
        env = {"PYTHONIOENCODING": "utf-8", "PYTHONHASHSEED": "0"}
        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-S", "-c", _WRAPPER],
                input=payload,
                text=True,
                capture_output=True,
                timeout=self.limits.wall_time_seconds,
                env=env,
                close_fds=True,
                preexec_fn=_resource_limiter(self.limits),
            )
        except subprocess.TimeoutExpired as exc:
            raise FeatureSandboxError("generated feature exceeded sandbox wall-time limit") from exc
        if completed.returncode != 0:
            error = completed.stderr.strip()[-4000:]
            raise FeatureSandboxError(f"generated feature failed in sandbox: {error or 'unknown error'}")
        if len(completed.stdout.encode("utf-8")) > self.limits.max_output_bytes:
            raise FeatureSandboxError("generated feature output exceeded max_output_bytes")
        try:
            decoded = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise FeatureSandboxError("sandbox returned invalid JSON") from exc
        values = decoded.get("values") if isinstance(decoded, dict) else None
        if not isinstance(values, list):
            raise FeatureSandboxError("sandbox output does not contain a values list")
        expected_length = len(next(iter(request.inputs.values())))
        if len(values) != expected_length:
            raise FeatureSandboxError("feature output length must equal input length")
        normalized: list[float | None] = []
        for value in values:
            if value is None:
                normalized.append(None)
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                raise FeatureSandboxError("sandbox output contains a non-numeric value")
            else:
                number = float(value)
                if not math.isfinite(number):
                    raise FeatureSandboxError("sandbox output contains a non-finite value")
                normalized.append(number)
        return FeatureSandboxResult(tuple(normalized), completed.stdout, completed.stderr)
