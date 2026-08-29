from __future__ import annotations

import hashlib
import json
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

ConfigDomain = Literal[
    "presentation",
    "runtime",
    "research_protocol",
    "execution_protocol",
    "operational_guardrail",
    "secret_reference",
]
ConfigMutationPolicy = Literal[
    "presentation_only",
    "restart_or_new_run",
    "new_identity_required",
    "governed_change_required",
    "host_secret_binding_only",
]
CommandLevel = Literal["L0", "L1", "L2", "L3"]
CommandGatewayReadiness = Literal[
    "catalog_only",
    "adapter_required",
    "application_service_ready",
]

CONFIG_REGISTRY_SCHEMA = "finagent.workbench.config-registry.v1"
CONFIG_DESCRIPTOR_SCHEMA = "finagent.workbench.config-descriptor.v1"
CONFIG_SNAPSHOT_SCHEMA = "finagent.workbench.config-snapshot.v1"
CONFIG_DIFF_SCHEMA = "finagent.workbench.config-diff.v1"
COMMAND_CATALOG_SCHEMA = "finagent.workbench.command-catalog.v1"
COMMAND_SPEC_SCHEMA = "finagent.workbench.command-spec.v1"
COMMAND_INTENT_SCHEMA = "finagent.workbench.command-intent.v1"
COMMAND_RUN_SCHEMA = "finagent.workbench.command-run.v1"
COMMAND_RESULT_SCHEMA = "finagent.workbench.command-result.v1"

_REDACTED = "<redacted>"
_SECRET_FILE_REFERENCE = "<secret-file-reference>"
_FORBIDDEN_SECRET_KEYS = {
    "api_key",
    "api_secret",
    "secret_key",
    "token",
    "password",
    "credential",
    "credentials",
    "access_key",
    "private_key",
}
_SAFE_SECRET_REFERENCE_KEYS = {
    "secret_id",
    "secrets_file",
    "api_key_env",
    "token_env",
}
_RUNTIME_KEYS = {
    "root",
    "frozen_manifest",
    "supplement_root",
    "state_dir",
    "report_path",
    "ledger_path",
    "a2p6_report",
    "feature_store",
    "llm_config_path",
    "default_profile",
    "mode",
}
_EXECUTION_PREFIXES = (
    "slippage_",
    "broker_",
    "stamp_duty_",
    "transfer_fee_",
    "exchange_",
    "regulatory_",
    "pass_through_",
    "require_price_limits",
    "commission_",
    "fill_",
)
_GUARDRAIL_PREFIXES = (
    "policy_",
    "limit_",
    "max_participation",
    "kill_switch",
)
_SUPPORTED_SECTIONS: dict[str, tuple[str, ConfigDomain]] = {
    "local_ashare": (
        "Local A-share dataset certification",
        "runtime",
    ),
    "local_ashare_robust_research": (
        "A2.6 robust A-share research",
        "research_protocol",
    ),
    "local_ashare_factor_research": (
        "A2/A2.5 A-share factor research",
        "research_protocol",
    ),
    "local_ashare_research_smoke": (
        "A-share research smoke",
        "research_protocol",
    ),
    "ashare_portfolio_validation": (
        "A4 portfolio validation",
        "research_protocol",
    ),
    "ashare_execution_smoke": (
        "A3 execution smoke",
        "execution_protocol",
    ),
    "llm": ("LLM routing", "runtime"),
    "market_data": ("Market-data routing", "runtime"),
}


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _digest(prefix: str, value: object, length: int = 32) -> str:
    digest = hashlib.sha256(_canonical_json(value)).hexdigest()[:length]
    return f"{prefix}-{digest}"


def _leaf_name(field_path: str) -> str:
    raw = field_path.rsplit(".", 1)[-1]
    return raw.split("[", 1)[0].lower()


def _contains_secret_filename(path: Path) -> bool:
    lowered = path.name.lower()
    return "secret" in lowered or "credential" in lowered


def _is_forbidden_secret_key(field_path: str) -> bool:
    leaf = _leaf_name(field_path)
    if leaf in _SAFE_SECRET_REFERENCE_KEYS:
        return False
    return (
        leaf in _FORBIDDEN_SECRET_KEYS
        or leaf.endswith("_password")
        or leaf.endswith("_token")
        or leaf.endswith("_secret")
        or leaf.endswith("_api_key")
    )


def _flatten(value: Mapping[str, object], prefix: str = "") -> dict[str, object]:
    output: dict[str, object] = {}
    for raw_key, raw_value in sorted(value.items(), key=lambda item: str(item[0])):
        key = str(raw_key)
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(raw_value, Mapping):
            output.update(_flatten(raw_value, path))
        else:
            output[path] = raw_value
    return output


def _json_scalar(value: object) -> JsonScalar:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _sanitize_json(value: object, field_path: str) -> tuple[JsonValue, tuple[str, ...]]:
    """Convert to JSON-compatible data while recursively redacting credential values."""

    leaf = _leaf_name(field_path)
    if leaf == "secrets_file":
        return _SECRET_FILE_REFERENCE, (field_path,)
    if _is_forbidden_secret_key(field_path):
        return _REDACTED, (field_path,)
    if isinstance(value, Mapping):
        output: dict[str, JsonValue] = {}
        redacted: list[str] = []
        for raw_key, raw_value in sorted(value.items(), key=lambda item: str(item[0])):
            key = str(raw_key)
            nested_path = f"{field_path}.{key}" if field_path else key
            sanitized, nested_redacted = _sanitize_json(raw_value, nested_path)
            output[key] = sanitized
            redacted.extend(nested_redacted)
        return output, tuple(redacted)
    if isinstance(value, (list, tuple)):
        output_list: list[JsonValue] = []
        redacted = []
        for index, raw_value in enumerate(value):
            nested_path = f"{field_path}[{index}]"
            sanitized, nested_redacted = _sanitize_json(raw_value, nested_path)
            output_list.append(sanitized)
            redacted.extend(nested_redacted)
        return output_list, tuple(redacted)
    return _json_scalar(value), ()


def _domain_for(
    section: str,
    field_path: str,
    default: ConfigDomain,
) -> ConfigDomain:
    leaf = _leaf_name(field_path)
    if leaf in _SAFE_SECRET_REFERENCE_KEYS or _is_forbidden_secret_key(field_path):
        return "secret_reference"
    if leaf in _RUNTIME_KEYS or leaf.endswith("_path") or leaf.endswith("_dir"):
        return "runtime"
    if section in {"local_ashare", "llm", "market_data"}:
        return "runtime"
    if section in {"ashare_execution_smoke", "ashare_portfolio_validation"} and (
        leaf.startswith(_EXECUTION_PREFIXES)
        or leaf in {"cash_fallback_on_model_error"}
    ):
        return "execution_protocol"
    if section == "ashare_portfolio_validation" and leaf.startswith(
        _GUARDRAIL_PREFIXES
    ):
        return "operational_guardrail"
    return default


def _mutation_policy(domain: ConfigDomain) -> ConfigMutationPolicy:
    return {
        "presentation": "presentation_only",
        "runtime": "restart_or_new_run",
        "research_protocol": "new_identity_required",
        "execution_protocol": "new_identity_required",
        "operational_guardrail": "governed_change_required",
        "secret_reference": "host_secret_binding_only",
    }[domain]


def _value_type(value: JsonValue) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _field_was_redacted(field_path: str, redacted_paths: Sequence[str]) -> bool:
    return any(
        value == field_path
        or value.startswith(f"{field_path}.")
        or value.startswith(f"{field_path}[")
        for value in redacted_paths
    )


@dataclass(frozen=True, slots=True)
class ConfigFieldSpec:
    field_path: str
    label: str
    value_type: str
    domain: ConfigDomain
    mutation_policy: ConfigMutationPolicy
    required: bool
    secret_redacted: bool = False
    description: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ConfigDescriptor:
    descriptor_id: str
    title: str
    section: str
    default_domain: ConfigDomain
    fields: tuple[ConfigFieldSpec, ...]
    snapshot_ids: tuple[str, ...]
    read_only: bool = True
    schema_version: str = CONFIG_DESCRIPTOR_SCHEMA

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["fields"] = [field.to_dict() for field in self.fields]
        payload["snapshot_ids"] = list(self.snapshot_ids)
        return payload


@dataclass(frozen=True, slots=True)
class ConfigSnapshot:
    snapshot_id: str
    descriptor_id: str
    section: str
    source_uri: str
    source_sha256: str
    values: Mapping[str, JsonValue]
    domains: Mapping[str, ConfigDomain]
    mutation_policies: Mapping[str, ConfigMutationPolicy]
    redacted_fields: tuple[str, ...]
    read_only: bool = True
    schema_version: str = CONFIG_SNAPSHOT_SCHEMA

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "descriptor_id": self.descriptor_id,
            "section": self.section,
            "source_uri": self.source_uri,
            "source_sha256": self.source_sha256,
            "values": dict(self.values),
            "domains": dict(self.domains),
            "mutation_policies": dict(self.mutation_policies),
            "redacted_fields": list(self.redacted_fields),
            "read_only": self.read_only,
        }


@dataclass(frozen=True, slots=True)
class ConfigDiffItem:
    field_path: str
    before: JsonValue | None
    after: JsonValue | None
    domain: ConfigDomain
    mutation_policy: ConfigMutationPolicy
    requires_new_identity: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ConfigDiff:
    diff_id: str
    descriptor_id: str
    left_snapshot_id: str
    right_snapshot_id: str
    changes: tuple[ConfigDiffItem, ...]
    requires_new_identity: bool
    read_only: bool = True
    schema_version: str = CONFIG_DIFF_SCHEMA

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "diff_id": self.diff_id,
            "descriptor_id": self.descriptor_id,
            "left_snapshot_id": self.left_snapshot_id,
            "right_snapshot_id": self.right_snapshot_id,
            "changes": [item.to_dict() for item in self.changes],
            "requires_new_identity": self.requires_new_identity,
            "read_only": self.read_only,
        }


@dataclass(frozen=True, slots=True)
class ConfigRegistryProjection:
    descriptors: tuple[ConfigDescriptor, ...]
    snapshots: tuple[ConfigSnapshot, ...]
    warnings: tuple[str, ...]
    read_only: bool = True
    schema_version: str = CONFIG_REGISTRY_SCHEMA

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "read_only": self.read_only,
            "descriptors": [item.to_dict() for item in self.descriptors],
            "snapshots": [item.to_dict() for item in self.snapshots],
            "warnings": list(self.warnings),
        }


class ConfigRegistry:
    """Read-only projection of allowlisted public FinAgent TOML configuration."""

    def __init__(self, roots: Sequence[str | Path]) -> None:
        self._roots = tuple(Path(root).expanduser() for root in roots)
        self._projection = self._build()
        self._descriptors = {
            item.descriptor_id: item for item in self._projection.descriptors
        }
        self._snapshots = {
            item.snapshot_id: item for item in self._projection.snapshots
        }

    @property
    def projection(self) -> ConfigRegistryProjection:
        return self._projection

    def descriptor(self, descriptor_id: str) -> ConfigDescriptor:
        try:
            return self._descriptors[descriptor_id]
        except KeyError as exc:
            raise KeyError(f"config descriptor not found: {descriptor_id}") from exc

    def snapshot(self, snapshot_id: str) -> ConfigSnapshot:
        try:
            return self._snapshots[snapshot_id]
        except KeyError as exc:
            raise KeyError(f"config snapshot not found: {snapshot_id}") from exc

    def snapshots(
        self,
        descriptor_id: str | None = None,
    ) -> tuple[ConfigSnapshot, ...]:
        if descriptor_id is None:
            return self._projection.snapshots
        self.descriptor(descriptor_id)
        return tuple(
            item
            for item in self._projection.snapshots
            if item.descriptor_id == descriptor_id
        )

    def diff(self, left_snapshot_id: str, right_snapshot_id: str) -> ConfigDiff:
        left = self.snapshot(left_snapshot_id)
        right = self.snapshot(right_snapshot_id)
        if left.descriptor_id != right.descriptor_id:
            raise ValueError("config diff requires snapshots from the same descriptor")
        changes: list[ConfigDiffItem] = []
        for field_path in sorted(set(left.values) | set(right.values)):
            before = left.values.get(field_path)
            after = right.values.get(field_path)
            if before == after:
                continue
            domain = right.domains.get(field_path) or left.domains[field_path]
            policy = (
                right.mutation_policies.get(field_path)
                or left.mutation_policies[field_path]
            )
            changes.append(
                ConfigDiffItem(
                    field_path=field_path,
                    before=before,
                    after=after,
                    domain=domain,
                    mutation_policy=policy,
                    requires_new_identity=domain
                    in {"research_protocol", "execution_protocol"},
                )
            )
        requires_new_identity = any(item.requires_new_identity for item in changes)
        diff_id = _digest(
            "config-diff",
            {
                "left": left.snapshot_id,
                "right": right.snapshot_id,
                "changes": [item.to_dict() for item in changes],
            },
        )
        return ConfigDiff(
            diff_id=diff_id,
            descriptor_id=left.descriptor_id,
            left_snapshot_id=left.snapshot_id,
            right_snapshot_id=right.snapshot_id,
            changes=tuple(changes),
            requires_new_identity=requires_new_identity,
        )

    def _candidate_files(self) -> tuple[tuple[int, Path, Path], ...]:
        output: list[tuple[int, Path, Path]] = []
        for root_index, root in enumerate(self._roots):
            if root.is_file():
                output.append((root_index, root.parent, root))
                continue
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*.toml")):
                output.append((root_index, root, path))
        return tuple(output)

    def _build(self) -> ConfigRegistryProjection:
        warnings: list[str] = []
        snapshot_by_id: dict[str, ConfigSnapshot] = {}
        fields_by_descriptor: dict[
            str,
            dict[str, tuple[ConfigDomain, ConfigMutationPolicy]],
        ] = {}
        field_types: dict[tuple[str, str], set[str]] = {}
        field_redacted: dict[tuple[str, str], bool] = {}
        field_presence: dict[tuple[str, str], int] = {}
        snapshot_ids_by_descriptor: dict[str, list[str]] = {}

        for root_index, root, path in self._candidate_files():
            if _contains_secret_filename(path):
                warnings.append(
                    "secret-like config excluded without parsing: "
                    f"config-root-{root_index}/{path.name}"
                )
                continue
            try:
                raw_bytes = path.read_bytes()
                payload = tomllib.loads(raw_bytes.decode("utf-8"))
            except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
                warnings.append(
                    f"config skipped: {path.name}: {type(exc).__name__}"
                )
                continue
            if not isinstance(payload, dict):
                continue
            relative = path.relative_to(root).as_posix() if path != root else path.name
            source_uri = f"config://root-{root_index}/{relative}"
            source_sha256 = hashlib.sha256(raw_bytes).hexdigest()

            for section, (_, default_domain) in _SUPPORTED_SECTIONS.items():
                raw_section = payload.get(section)
                if not isinstance(raw_section, dict):
                    continue
                flattened = _flatten(raw_section)
                sanitized: dict[str, JsonValue] = {}
                domains: dict[str, ConfigDomain] = {}
                policies: dict[str, ConfigMutationPolicy] = {}
                all_redacted_paths: list[str] = []

                for field_path, raw_value in flattened.items():
                    value, redacted_paths = _sanitize_json(raw_value, field_path)
                    domain = _domain_for(section, field_path, default_domain)
                    policy = _mutation_policy(domain)
                    sanitized[field_path] = value
                    domains[field_path] = domain
                    policies[field_path] = policy
                    all_redacted_paths.extend(redacted_paths)

                snapshot_id = _digest(
                    "config-snapshot",
                    {
                        "descriptor_id": section,
                        "source_sha256": source_sha256,
                        "values": sanitized,
                    },
                )
                if snapshot_id in snapshot_by_id:
                    warnings.append(f"duplicate config snapshot ignored: {source_uri}")
                    continue

                snapshot = ConfigSnapshot(
                    snapshot_id=snapshot_id,
                    descriptor_id=section,
                    section=section,
                    source_uri=source_uri,
                    source_sha256=source_sha256,
                    values=sanitized,
                    domains=domains,
                    mutation_policies=policies,
                    redacted_fields=tuple(sorted(set(all_redacted_paths))),
                )
                snapshot_by_id[snapshot_id] = snapshot
                snapshot_ids_by_descriptor.setdefault(section, []).append(snapshot_id)
                descriptor_fields = fields_by_descriptor.setdefault(section, {})
                for field_path, value in sanitized.items():
                    descriptor_fields[field_path] = (
                        domains[field_path],
                        policies[field_path],
                    )
                    field_key = (section, field_path)
                    field_types.setdefault(field_key, set()).add(_value_type(value))
                    field_redacted[field_key] = field_redacted.get(
                        field_key,
                        False,
                    ) or _field_was_redacted(field_path, all_redacted_paths)
                    field_presence[field_key] = field_presence.get(field_key, 0) + 1

        descriptors: list[ConfigDescriptor] = []
        for descriptor_id in sorted(fields_by_descriptor):
            title, default_domain = _SUPPORTED_SECTIONS[descriptor_id]
            snapshot_ids = tuple(sorted(snapshot_ids_by_descriptor[descriptor_id]))
            fields: list[ConfigFieldSpec] = []
            for field_path in sorted(fields_by_descriptor[descriptor_id]):
                domain, policy = fields_by_descriptor[descriptor_id][field_path]
                types = field_types[(descriptor_id, field_path)]
                fields.append(
                    ConfigFieldSpec(
                        field_path=field_path,
                        label=field_path.replace("_", " "),
                        value_type=next(iter(types)) if len(types) == 1 else "mixed",
                        domain=domain,
                        mutation_policy=policy,
                        required=(
                            field_presence[(descriptor_id, field_path)]
                            == len(snapshot_ids)
                        ),
                        secret_redacted=field_redacted[(descriptor_id, field_path)],
                    )
                )
            descriptors.append(
                ConfigDescriptor(
                    descriptor_id=descriptor_id,
                    title=title,
                    section=descriptor_id,
                    default_domain=default_domain,
                    fields=tuple(fields),
                    snapshot_ids=snapshot_ids,
                )
            )

        snapshots = sorted(
            snapshot_by_id.values(),
            key=lambda item: (
                item.descriptor_id,
                item.source_uri,
                item.snapshot_id,
            ),
        )
        return ConfigRegistryProjection(
            descriptors=tuple(descriptors),
            snapshots=tuple(snapshots),
            warnings=tuple(sorted(set(warnings))),
        )


@dataclass(frozen=True, slots=True)
class CommandSpec:
    command_id: str
    title: str
    description: str
    level: CommandLevel
    config_descriptor_ids: tuple[str, ...]
    binding_kind: str
    binding_ref: str
    gateway_readiness: CommandGatewayReadiness
    produces: tuple[str, ...]
    requires_confirmation: bool
    execution_enabled: bool = False
    catalog_only: bool = True
    schema_version: str = COMMAND_SPEC_SCHEMA

    def __post_init__(self) -> None:
        if self.level not in {"L0", "L1"}:
            raise ValueError(
                "generic Workbench command catalog may contain only L0/L1 commands"
            )
        if self.execution_enabled:
            raise ValueError("command execution remains disabled until V3-2C gateway")

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["config_descriptor_ids"] = list(self.config_descriptor_ids)
        payload["produces"] = list(self.produces)
        return payload


@dataclass(frozen=True, slots=True)
class CommandIntent:
    intent_id: str
    command_id: str
    config_snapshot_id: str | None
    context: Mapping[str, str]
    requested_by: str
    state: Literal["draft", "validated", "rejected"]
    schema_version: str = COMMAND_INTENT_SCHEMA

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "context": dict(self.context)}


@dataclass(frozen=True, slots=True)
class CommandRun:
    command_run_id: str
    intent_id: str
    command_id: str
    state: Literal["planned", "running", "succeeded", "failed", "rejected"]
    started_at: str | None
    finished_at: str | None
    schema_version: str = COMMAND_RUN_SCHEMA

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CommandResult:
    command_run_id: str
    status: Literal["succeeded", "failed", "rejected"]
    evidence_ids: tuple[str, ...]
    message: str
    schema_version: str = COMMAND_RESULT_SCHEMA

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["evidence_ids"] = list(self.evidence_ids)
        return payload


_DEFAULT_COMMAND_SPECS = (
    CommandSpec(
        command_id="config.validate",
        title="Validate configuration",
        description=(
            "Validate a public configuration snapshot before any governed "
            "execution is considered."
        ),
        level="L0",
        config_descriptor_ids=tuple(sorted(_SUPPORTED_SECTIONS)),
        binding_kind="application_service",
        binding_ref=(
            "finagent.application.control_services.ConfigValidationApplicationService"
        ),
        gateway_readiness="application_service_ready",
        produces=("ConfigValidationEvidence",),
        requires_confirmation=False,
    ),
    CommandSpec(
        command_id="data.certify_local_ashare",
        title="Certify local A-share data",
        description=(
            "Run deterministic local-data certification without research or "
            "trading authority."
        ),
        level="L0",
        config_descriptor_ids=("local_ashare",),
        binding_kind="application_service",
        binding_ref=(
            "finagent.application.control_services."
            "LocalAshareCertificationApplicationService"
        ),
        gateway_readiness="application_service_ready",
        produces=("LocalAshareDataCertification",),
        requires_confirmation=False,
    ),
    CommandSpec(
        command_id="research.run_development",
        title="Run development factor research",
        description=(
            "Future governed L1 entry for bounded A2/A2.5 development research "
            "only."
        ),
        level="L1",
        config_descriptor_ids=("local_ashare_factor_research",),
        binding_kind="cli_orchestration",
        binding_ref="scripts/run_local_ashare_factor_research.py",
        gateway_readiness="adapter_required",
        produces=("FactorResearchReport",),
        requires_confirmation=True,
    ),
    CommandSpec(
        command_id="research.run_a2p6",
        title="Run A2.6 robust research",
        description=(
            "Future governed L1 entry for preregistered robust ResearchProgram "
            "execution."
        ),
        level="L1",
        config_descriptor_ids=("local_ashare_robust_research",),
        binding_kind="cli_orchestration",
        binding_ref="scripts/run_local_ashare_robust_research.py",
        gateway_readiness="adapter_required",
        produces=("AshareRobustResearchProgramResult",),
        requires_confirmation=True,
    ),
    CommandSpec(
        command_id="portfolio.run_a4",
        title="Run A4 portfolio validation",
        description=(
            "Future governed L1 entry for execution-aware internal A4 validation."
        ),
        level="L1",
        config_descriptor_ids=("ashare_portfolio_validation",),
        binding_kind="cli_orchestration",
        binding_ref="scripts/run_ashare_portfolio_validation.py",
        gateway_readiness="adapter_required",
        produces=("AsharePortfolioValidationResult",),
        requires_confirmation=True,
    ),
    CommandSpec(
        command_id="review.export_bundle",
        title="Export review bundle",
        description=(
            "Deterministic L0 human-review bundle export through an in-process "
            "application service."
        ),
        level="L0",
        config_descriptor_ids=(),
        binding_kind="application_service",
        binding_ref=(
            "finagent.application.control_services.ReviewBundleExportApplicationService"
        ),
        gateway_readiness="application_service_ready",
        produces=("HumanReviewBundle",),
        requires_confirmation=False,
    ),
)


class CommandCatalog:
    def __init__(
        self,
        specs: Sequence[CommandSpec] = _DEFAULT_COMMAND_SPECS,
    ) -> None:
        self._specs = tuple(specs)
        self._by_id = {spec.command_id: spec for spec in self._specs}
        if len(self._by_id) != len(self._specs):
            raise ValueError("command catalog contains duplicate command_id")

    @property
    def specs(self) -> tuple[CommandSpec, ...]:
        return self._specs

    def get(self, command_id: str) -> CommandSpec:
        try:
            return self._by_id[command_id]
        except KeyError as exc:
            raise KeyError(f"command not found: {command_id}") from exc

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": COMMAND_CATALOG_SCHEMA,
            "read_only": True,
            "execution_enabled": False,
            "control_plane_enabled": False,
            "items": [spec.to_dict() for spec in self._specs],
            "forbidden_authority": [
                "production_reserve",
                "strategy_promotion",
                "paper_mutation",
                "broker_order",
                "live_capital",
                "arbitrary_shell",
                "arbitrary_python",
            ],
        }


def default_command_catalog() -> CommandCatalog:
    return CommandCatalog()
