from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
import sys
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Sequence

from finagent.agents.generated_features import FeatureCodeValidator, FeatureSpec
from finagent.domain._validation import require_non_empty

Number = int | float


@dataclass(frozen=True, slots=True)
class FeatureSandboxLimits:
    wall_time_seconds: float = 3.0
    cpu_time_seconds: int = 2
    memory_mb: int = 512
    max_output_bytes: int = 1_000_000

    def __post_init__(self) -> None:
        if (
            self.wall_time_seconds <= 0
            or self.cpu_time_seconds < 1
            or self.memory_mb < 64
            or self.max_output_bytes < 1024
        ):
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
batch_inputs = payload["batch_inputs"]
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
outputs = []
for inputs in batch_inputs:
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
    outputs.append(normalized)
print(json.dumps({"batch_values": outputs}, separators=(",", ":"), allow_nan=False))
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
    """Restricted subprocess for generated feature smoke tests and PIT batches.

    Static validation remains the first boundary. ``run_batch`` compiles the already
    validated feature source once per subprocess and evaluates independent PIT input
    windows without exposing one window to another.  Batching improves scale without
    weakening the causal data boundary.

    This is not a kernel/container sandbox and must not be described as one.
    """

    def __init__(
        self,
        *,
        validator: FeatureCodeValidator | None = None,
        limits: FeatureSandboxLimits = FeatureSandboxLimits(),
    ) -> None:
        self.validator = validator or FeatureCodeValidator()
        self.limits = limits

    def run(self, request: FeatureSandboxRequest) -> FeatureSandboxResult:
        return self.run_batch((request,))[0]

    def _prepare_batch(
        self,
        requests: Sequence[FeatureSandboxRequest],
    ) -> tuple[tuple[FeatureSandboxRequest, ...], str]:
        requests = tuple(requests)
        if not requests:
            return (), ""
        first = requests[0]
        for request in requests:
            if request.source != first.source or request.spec != first.spec:
                raise ValueError("batched sandbox requests must share FeatureSpec and source")
        self.validator.validate(first.source)
        payload = json.dumps(
            {
                "source": first.source,
                "batch_inputs": [
                    {key: list(values) for key, values in request.inputs.items()}
                    for request in requests
                ],
            },
            allow_nan=False,
        )
        return requests, payload

    def _decode_batch(
        self,
        requests: tuple[FeatureSandboxRequest, ...],
        *,
        stdout: str,
        stderr: str,
        returncode: int,
    ) -> tuple[FeatureSandboxResult, ...]:
        if returncode != 0:
            error = stderr.strip()[-4000:]
            raise FeatureSandboxError(
                f"generated feature failed in sandbox: {error or 'unknown error'}"
            )
        if len(stdout.encode("utf-8")) > self.limits.max_output_bytes:
            raise FeatureSandboxError("generated feature output exceeded max_output_bytes")
        try:
            decoded = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise FeatureSandboxError("sandbox returned invalid JSON") from exc
        batch_values = decoded.get("batch_values") if isinstance(decoded, dict) else None
        if not isinstance(batch_values, list) or len(batch_values) != len(requests):
            raise FeatureSandboxError("sandbox output does not contain the expected batch_values")

        results: list[FeatureSandboxResult] = []
        for request, values in zip(requests, batch_values):
            if not isinstance(values, list):
                raise FeatureSandboxError("sandbox batch item is not a values list")
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
            results.append(FeatureSandboxResult(tuple(normalized)))
        return tuple(results)

    def _start_process(self) -> subprocess.Popen[str]:
        env = {"PYTHONIOENCODING": "utf-8", "PYTHONHASHSEED": "0"}
        return subprocess.Popen(
            [sys.executable, "-I", "-S", "-c", _WRAPPER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            close_fds=True,
            preexec_fn=_resource_limiter(self.limits),
        )

    def _communicate(
        self,
        process: subprocess.Popen[str],
        payload: str,
        started_at: float,
    ) -> tuple[str, str, int]:
        remaining = max(0.01, self.limits.wall_time_seconds - (time.monotonic() - started_at))
        try:
            stdout, stderr = process.communicate(input=payload, timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise FeatureSandboxError(
                "generated feature exceeded sandbox wall-time limit"
            ) from exc
        return stdout, stderr, int(process.returncode or 0)

    def run_batch(
        self,
        requests: Sequence[FeatureSandboxRequest],
    ) -> tuple[FeatureSandboxResult, ...]:
        prepared, payload = self._prepare_batch(requests)
        if not prepared:
            return ()
        started_at = time.monotonic()
        process = self._start_process()
        stdout, stderr, returncode = self._communicate(process, payload, started_at)
        return self._decode_batch(
            prepared, stdout=stdout, stderr=stderr, returncode=returncode
        )

    def run_batches(
        self,
        batches: Sequence[Sequence[FeatureSandboxRequest]],
        *,
        max_workers: int,
    ) -> tuple[tuple[FeatureSandboxResult, ...], ...]:
        """Execute independent batches concurrently without nested Python workers.

        Child processes are created on the caller thread before any communication
        threads start. This keeps the POSIX ``preexec_fn`` resource limiter out of
        multithreaded ``Popen`` calls while still allowing multiple generated-feature
        subprocesses to compute concurrently.
        """

        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        prepared_batches = [self._prepare_batch(batch) for batch in batches]
        if not prepared_batches:
            return ()
        output: list[tuple[FeatureSandboxResult, ...]] = []
        for start in range(0, len(prepared_batches), max_workers):
            wave = prepared_batches[start : start + max_workers]
            wave_output: list[tuple[FeatureSandboxResult, ...] | None] = [None] * len(wave)
            running: list[
                tuple[int, tuple[FeatureSandboxRequest, ...], str, subprocess.Popen[str], float]
            ] = []
            try:
                for wave_index, (requests, payload) in enumerate(wave):
                    if not requests:
                        wave_output[wave_index] = ()
                        continue
                    started_at = time.monotonic()
                    running.append(
                        (wave_index, requests, payload, self._start_process(), started_at)
                    )
                if running:
                    with ThreadPoolExecutor(
                        max_workers=len(running),
                        thread_name_prefix="finagent-sandbox-io",
                    ) as executor:
                        futures = [
                            executor.submit(self._communicate, process, payload, started_at)
                            for _, _, payload, process, started_at in running
                        ]
                        for (wave_index, requests, _, _, _), future in zip(
                            running, futures
                        ):
                            stdout, stderr, returncode = future.result()
                            wave_output[wave_index] = self._decode_batch(
                                requests,
                                stdout=stdout,
                                stderr=stderr,
                                returncode=returncode,
                            )
                if any(result is None for result in wave_output):
                    raise FeatureSandboxError("sandbox batch wave produced incomplete results")
                output.extend(result for result in wave_output if result is not None)
            except Exception:
                for _, _, _, process, _ in running:
                    if process.poll() is None:
                        process.kill()
                raise
        return tuple(output)
