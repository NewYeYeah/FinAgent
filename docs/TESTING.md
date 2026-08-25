# FinAgent v1.0.1 Testing Guide

## 1. Testing Philosophy

FinAgent testing is divided into:

```
Environment Validation
        |
Unit Test
        |
Quant Core Validation
        |
Agent Integration Test
        |
Paper Trading Test
        |
LLM Benchmark
```

The purpose is reproducibility, not only code coverage.

---

## 2. Environment Setup

FinAgent requires an isolated Python environment.

Supported environment:

- Ubuntu 22.04/24.04
- Python 3.11
- Conda recommended

Create environment:

```bash
conda env create -f environment/environment.yml
./scripts/finagent.sh --check
```

Verify:

```bash
python --version
```

Expected:

```
Python 3.11.x
```

Verify package import:

```bash
python -c "from finagent.domain.assets import AssetId; print('FinAgent import OK')"
```

Verify dependencies:

```bash
pip check
```

Expected:

```
No broken requirements found
```

---

## 3. ROS2 Isolation

FinAgent is not a ROS2 package. ROS 2 setup files may inject Python modules,
pytest plugins and shared-library paths into a shell.

Use the single wrapper even if the current terminal was previously contaminated:

```bash
./scripts/finagent.sh --check
./scripts/finagent.sh
```

The interactive command opens a child shell. It cannot and does not rewrite the
parent terminal. For one-off work, pass any command directly:

```bash
./scripts/finagent.sh python -m pytest -q
./scripts/finagent.sh ruff check src tests --select E9,F63,F7,F82
```

All project test launchers should delegate to `scripts/finagent.sh` or source
`scripts/lib/finagent_env.sh`; they should not duplicate environment cleanup.

---

## 4. Core Test

Run:

```bash
./scripts/run_tests.sh -v
```

Coverage target:

```bash
./scripts/run_tests.sh --cov=finagent --cov-report=term
```

Validated components:

- Asset model
- Dataset contract
- Alpha model
- Risk model
- Portfolio construction
- Execution state
- Supervisor
- Evidence memory

---

## 5. Quant Core Validation

### PIT validation

Verify:

- feature generation only uses information available at timestamp t
- future label mutation cannot change formation weights

Expected:

```
formation result unchanged
```

### Universe validation

Verify that dynamic eligibility does not include:

- future listed assets
- future index members
- future information

### Turnover validation

All modules must use consistent turnover semantics:

```
gross traded weight = sum(abs(delta weight))
one-way turnover = gross traded weight / 2
```

Transaction cost must use gross traded weight.

---

## 6. Code Quality Validation

Run:

```bash
./scripts/finagent.sh ruff check .
./scripts/finagent.sh mypy src
./scripts/finagent.sh python -m build
```

---

## 7. LLM Agent Integration Test

FinAgent supports external LLM providers through API adapters.

Recommended providers:

|Provider|Purpose|
|-|-|
|SiliconFlow|low-cost batch research|
|DeepSeek API|Chinese financial reasoning baseline|
|OpenAI API|high capability baseline|

Example benchmark structure:

```
experiments/llm/
    siliconflow/
    deepseek/
    openai/
```

Each episode records:

```json
{
  "model": "deepseek-chat",
  "cost": 0,
  "research_plan_valid": true,
  "feature_generated": true,
  "backtest_completed": true
}
```

Recommended first benchmark:

- 100 research episodes per provider
- identical prompts
- identical dataset
- identical validation rules

---

## 8. Paper Trading Validation

Pipeline:

```
Signal
 |
Portfolio
 |
OrderPlanner
 |
PaperBroker
 |
Reconciliation
```

Test:

- duplicate order protection
- partial fill handling
- restart recovery
- kill switch
- approval expiry
- reconciliation failure

---

## 9. Release Checklist

Before release:

```bash
./scripts/run_tests.sh
./scripts/finagent.sh ruff check .
./scripts/finagent.sh mypy src
./scripts/finagent.sh python -m build
```

All checks must pass.

A release candidate should additionally complete:

- paper trading observation
- operational journal review
- acceptance report generation
