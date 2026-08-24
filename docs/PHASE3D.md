# Phase 3D — Restricted Generated Feature Programs

## Objective

Phase 3D extends FinAgent from selecting approved research templates to proposing and implementing new feature/factor code while preserving the existing deterministic research and trading boundaries.

The canonical path is:

```text
AgentTask
 -> LLMFeatureGenerator
 -> strict feature JSON
 -> FeatureSpec + source
 -> FeatureCodeValidator
 -> LocalFeatureSandbox smoke test
 -> GeneratedFeatureArtifact
 -> SQLiteGeneratedFeatureStore
 -> generated_feature_template(...)
 -> existing ResearchPlan / ExperimentFamily / validation path
```

## Feature contract

Generated code must define exactly:

```python
def compute_feature(inputs):
    ...
```

Inputs are approved PIT fields represented as equal-length sequences of finite numbers or `None`. Output must have identical length and contain finite numbers or `None` only.

The contract intentionally avoids pandas, filesystem objects, network clients, broker objects and FinAgent internal registries.

## New components

```text
FeatureSpec
FeatureCodePolicy
FeatureValidationReport
FeatureCodeValidator
GeneratedFeatureArtifact
SQLiteGeneratedFeatureStore

FeatureSandboxLimits
FeatureSandboxRequest
FeatureSandboxResult
LocalFeatureSandbox

LLMFeatureGenerationPolicy
LLMFeatureGenerationResult
LLMFeatureGenerator
generated_feature_template
```

## Static validation

The first validator rejects imports, arbitrary attributes, dunder access, dynamic execution, file access, classes, async constructs, global/nonlocal state, context managers, exception machinery and while loops. It also applies source/AST/comprehension limits.

Permitted calls are a finite builtin set and selected `math` functions. This deliberately narrows the generated language to numeric transforms rather than general Python programs.

## Restricted subprocess

The smoke-test runner uses a separate `python -I -S` process, a reduced builtin namespace and strict JSON transport. On POSIX it additionally applies CPU, virtual-memory, file-size and file-descriptor limits.

This runner is not advertised as container-grade isolation. It is sufficient for Phase 3D's constrained language because imports and arbitrary attribute traversal are rejected before execution. Container/seccomp/bubblewrap hardening can be added later if generated-code scope expands.

## LLM generation policy

The LLM may propose:

```text
feature id/name/description/hypothesis
approved input-field subset
bounded lookback
compute_feature source
```

It cannot propose:

```text
future-return/outer-test fields not on the input allowlist
research or statistical thresholds
portfolio weights
risk overrides
execution/fill behavior
broker actions
registry mutations
arbitrary imports/dependencies
```

Provider structured output is treated as untrusted. `LLMFeatureGenerator` repeats exact-field, identifier, input-field, lookback, AST and runtime validation locally.

## Artifact and lineage

Accepted source becomes an immutable `GeneratedFeatureArtifact`. Its digest incorporates the semantic spec, source digest, validator version, generator identity and deterministic smoke-test output digest.

`SQLiteGeneratedFeatureStore` preserves multiple immutable versions of a feature id by digest. The source is stored explicitly for later audit, replay and lineage analysis.

## Research integration

`generated_feature_template(...)` converts the validated feature into the already-existing `ExperimentTemplate` contract. It does not bypass experiment-family registration or validation.

The next integration step is to provide a real generated-feature evaluator that materializes these artifacts against PIT `ResearchDataset` panels and returns nested walk-forward metrics instead of synthetic fixtures.

## Validation

Phase 3D tests cover:

- valid bounded feature AST;
- import/file/dunder/wrong-function rejection;
- restricted-process execution;
- output shape enforcement;
- SQLite artifact round-trip;
- rejection of non-approved input fields;
- conversion of validated generated code into an existing `ExperimentTemplate`.

## Explicitly deferred

```text
container/seccomp namespace isolation
arbitrary package installation
multi-file generated projects
model-code generation
portfolio/risk/execution code generation
self-modifying validation code
broker connectivity
multi-Agent code review debates
```

The immediate next milestone is Phase 3.5: connect generated feature artifacts to real point-in-time feature materialization and nested quantitative evaluation.
