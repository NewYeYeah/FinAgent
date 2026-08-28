import json
from datetime import datetime, timezone

import pytest

from finagent.agents import (
    AgentTask,
    FeatureCodeValidationError,
    FeatureCodeValidator,
    FeatureSpec,
    LLMFeatureGenerationError,
    LLMFeatureGenerationPolicy,
    LLMFeatureGenerator,
    SQLiteGeneratedFeatureStore,
    StaticLLMProvider,
    generated_feature_template,
)
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.experiments import ArtifactRef, ArtifactType
from finagent.sandbox import FeatureSandboxError, FeatureSandboxRequest, LocalFeatureSandbox

NOW = datetime(2026, 8, 25, 0, 10, tzinfo=timezone.utc)
VALID_SOURCE = '''\ndef compute_feature(inputs):\n    close = inputs["close"]\n    return [None if i < 2 or close[i] is None or close[i-2] in (None, 0) else close[i] / close[i-2] - 1.0 for i in range(len(close))]\n'''


def _spec():
    return FeatureSpec(
        feature_id="mom2",
        name="Two-step momentum",
        description="Two observation close-price momentum",
        hypothesis="Short-horizon momentum contains predictive information",
        input_fields=("close",),
        lookback=3,
    )


def test_feature_validator_accepts_bounded_pure_function():
    report = FeatureCodeValidator().validate(VALID_SOURCE)
    assert report.node_count > 0
    assert len(report.source_digest) == 64


@pytest.mark.parametrize(
    "source",
    [
        'import os\ndef compute_feature(inputs):\n    return inputs["close"]',
        'def compute_feature(inputs):\n    return open("x").read()',
        'def compute_feature(inputs):\n    return [math.__dict__ for _ in range(len(inputs["close"]))]',
        'def other(inputs):\n    return inputs["close"]',
    ],
)
def test_feature_validator_rejects_unsafe_or_wrong_contract(source):
    with pytest.raises(FeatureCodeValidationError):
        FeatureCodeValidator().validate(source)


def test_local_sandbox_executes_and_validates_output_shape():
    sandbox = LocalFeatureSandbox()
    result = sandbox.run(FeatureSandboxRequest(_spec(), VALID_SOURCE, {"close": [100, 101, 102, 103]}))
    assert result.values[:2] == (None, None)
    assert result.values[2] == pytest.approx(0.02)
    assert len(result.output_digest) == 64


def test_local_sandbox_rejects_wrong_length_output():
    source = 'def compute_feature(inputs):\n    return [1.0]'
    with pytest.raises(FeatureSandboxError, match="output length"):
        LocalFeatureSandbox().run(FeatureSandboxRequest(_spec(), source, {"close": [1, 2, 3]}))


def test_generated_feature_store_round_trip(tmp_path):
    output = json.dumps({
        "feature_id": "mom2",
        "name": "Two-step momentum",
        "description": "Two observation close-price momentum",
        "hypothesis": "Momentum contains signal",
        "input_fields": ["close"],
        "lookback": 3,
        "source": VALID_SOURCE,
    })
    store = SQLiteGeneratedFeatureStore(tmp_path / "state.db")
    generator = LLMFeatureGenerator(
        provider=StaticLLMProvider(output),
        policy=LLMFeatureGenerationPolicy(model="static-model"),
        feature_store=store,
        clock=lambda: NOW,
        request_id_factory=lambda: "feature-request-1",
    )
    result = generator.generate(
        task=AgentTask("task-feature", "generate short-horizon momentum", NOW),
        approved_input_fields=("close", "volume"),
        smoke_inputs={"close": [100, 101, 102, 103], "volume": [10, 11, 12, 13]},
    )
    restored = store.get(result.artifact.digest)
    assert restored.digest == result.artifact.digest
    assert restored.spec.feature_id == "mom2"
    assert store.digests_for_feature("mom2") == (result.artifact.digest,)


def test_llm_feature_generator_rejects_unapproved_input_field():
    output = json.dumps({
        "feature_id": "bad",
        "name": "Bad",
        "description": "Bad input",
        "hypothesis": "none",
        "input_fields": ["future_return"],
        "lookback": 1,
        "source": 'def compute_feature(inputs):\n    return inputs["future_return"]',
    })
    generator = LLMFeatureGenerator(
        provider=StaticLLMProvider(output),
        policy=LLMFeatureGenerationPolicy(model="static-model"),
    )
    with pytest.raises(LLMFeatureGenerationError, match="policy-approved"):
        generator.generate(
            task=AgentTask("task-bad", "bad feature", NOW),
            approved_input_fields=("close",),
            smoke_inputs={"close": [1, 2, 3]},
        )


def test_validated_feature_bridges_to_existing_experiment_template(tmp_path):
    output = json.dumps({
        "feature_id": "mom2",
        "name": "Two-step momentum",
        "description": "Two observation close-price momentum",
        "hypothesis": "Momentum contains signal",
        "input_fields": ["close"],
        "lookback": 3,
        "source": VALID_SOURCE,
    })
    generator = LLMFeatureGenerator(
        provider=StaticLLMProvider(output),
        policy=LLMFeatureGenerationPolicy(model="static-model"),
        clock=lambda: NOW,
    )
    artifact = generator.generate(
        task=AgentTask("task-feature", "generate momentum", NOW),
        approved_input_fields=("close",),
        smoke_inputs={"close": [100, 101, 102, 103]},
    ).artifact
    template = generated_feature_template(
        artifact,
        template_id="generated-mom2",
        evaluator_id="generated-feature-evaluator",
        dataset=ArtifactRef("dataset", ArtifactType.DATASET, "v1", "dataset-digest"),
        universe=(AssetId("AAA", AssetType.EQUITY, "TEST", "USD"),),
    )
    assert template.code.digest == artifact.digest
    assert template.metadata["generated_feature_id"] == "mom2"
    assert template.parameter_names == frozenset()


def test_local_sandbox_executes_multiple_batches_concurrently():
    sandbox = LocalFeatureSandbox()
    batches = tuple(
        (
            FeatureSandboxRequest(
                _spec(),
                VALID_SOURCE,
                {"close": [100 + offset, 101 + offset, 102 + offset, 103 + offset]},
            ),
        )
        for offset in range(4)
    )
    results = sandbox.run_batches(batches, max_workers=2)
    assert len(results) == 4
    assert all(len(batch) == 1 for batch in results)
    assert results[0][0].values[2] == pytest.approx(0.02)


def test_local_sandbox_parallel_batches_preserve_empty_batch_positions():
    sandbox = LocalFeatureSandbox()
    request = FeatureSandboxRequest(_spec(), VALID_SOURCE, {"close": [100, 101, 102, 103]})
    results = sandbox.run_batches(((), (request,), ()), max_workers=2)
    assert results[0] == ()
    assert len(results[1]) == 1
    assert results[1][0].values[2] == pytest.approx(0.02)
    assert results[2] == ()
