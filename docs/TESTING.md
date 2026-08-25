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
conda activate finagent
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

FinAgent is not a ROS2 package.

Do not run:

```bash
source /opt/ros/jazzy/setup.bash
```

before testing.

ROS2 Python packages can inject pytest plugins and incompatible Python dependencies.

Recommended:

Terminal 1:

```
ROS2 workspace
```

Terminal 2:

```bash
conda activate finagent
python -m pytest
```

---

## 4. Core Test

Run:

```bash
python -m pytest -v
```

Coverage target:

```bash
python -m pytest --cov=finagent --cov-report=term
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
ruff check .
mypy src
python -m build
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
python -m pytest
ruff check .
mypy src
python -m build
```

All checks must pass.

A release candidate should additionally complete:

- paper trading observation
- operational journal review
- acceptance report generation
