# ADR-014 — Phase 3D Sandboxed Feature Code Boundary

Status: Accepted

Date: 2026-08-25

## Context

Phase 3C allows an LLM to propose bounded `ResearchPlan` objects, but all experiments still depend on pre-existing approved code artifacts. The next capability gap is research novelty: the system cannot yet create a feature/factor implementation that did not already exist in the template registry.

Allowing unrestricted LLM-generated Python would violate the project's core separation between probabilistic planning and deterministic quantitative controls. Generated code therefore requires a narrower contract than ordinary application Python.

## Decision

Phase 3D introduces generated feature programs with the only executable contract:

```python
def compute_feature(inputs):
    ...
    return values
```

where:

- `inputs` contains only policy-approved point-in-time feature fields;
- each field is an equal-length sequence of finite numbers or `None`;
- output must be a sequence with exactly the same length;
- output values must be finite numbers or `None`;
- warm-up observations may be `None`.

A generated program is accepted only through:

```text
LLM structured feature proposal
 -> exact local schema validation
 -> AST static validation
 -> restricted subprocess smoke test
 -> immutable GeneratedFeatureArtifact
 -> SQLiteGeneratedFeatureStore
 -> generated ExperimentTemplate
 -> existing ExperimentFamily / validation controls
```

## Static restrictions

`FeatureCodeValidator` requires exactly one top-level function named `compute_feature(inputs)` and rejects imports, classes, async functions, lambdas, global/nonlocal state, context managers, exception machinery, while loops, dynamic execution and unsafe builtins.

Attribute access is restricted to an explicit allowlist of `math` members. Calls are restricted to a small builtin allowlist or approved `math` members. Dunder names are rejected. Source size, AST node count and comprehension count are bounded.

Static validation is a security control and a reproducibility control; it is not a proof of semantic correctness or alpha validity.

## Sandbox decision

`LocalFeatureSandbox` runs already-validated code in a separate Python process with:

- isolated interpreter flags (`-I -S`);
- a reduced builtin dictionary without import/file/process/network primitives;
- only the standard-library `math` module exposed through AST-approved members;
- strict JSON input/output;
- wall-time timeout;
- POSIX CPU, address-space, file-size and file-descriptor limits when available;
- output length/type/finiteness validation.

This is deliberately described as a **restricted subprocess**, not a kernel/container sandbox. Static restrictions prevent generated code from importing socket/OS/process modules, but Phase 3D does not claim Linux namespace, seccomp or container isolation. Stronger OS isolation remains an optional later hardening step.

## Artifact identity

`GeneratedFeatureArtifact.digest` includes:

```text
FeatureSpec
source digest
validator version
smoke-output digest
generator identity
```

The artifact can emit both CODE and FACTOR `ArtifactRef` identities. Generated source is stored for audit and replay.

## Integration boundary

A validated feature can be converted into an existing `ExperimentTemplate` through `generated_feature_template(...)`. This preserves the Phase 3B/3C experiment path rather than inventing a second Agent execution mechanism.

Generated code cannot modify or replace:

```text
DataAdapter/PIT logic
statistical validation
portfolio optimizer
RiskGate
execution engine
ResearchRegistry
model lifecycle
broker adapters
```

## Consequences

Phase 3D makes novel feature implementation possible, but it does not make generated features trustworthy investment signals. They still require point-in-time data, nested/family validation, multiple-testing controls and normal model governance.

The next milestone should integrate generated features with the real numerical research/evaluator pipeline and historical feature materialization before expanding orchestration complexity.
