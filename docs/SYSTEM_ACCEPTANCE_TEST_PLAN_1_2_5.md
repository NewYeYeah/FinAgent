# FinAgent 1.2.5 系统验收测试计划

**文档版本：** v1.0  
**适用代码基线：** FinAgent 1.2.5  
**基线分支：** `main`  
**基线提交：** `4c4d03e31bdb8978b3c1a52a5614e47818a1935f`  
**适用系统：** Ubuntu 22.04/24.04、Windows 10/11 x64（原生 PowerShell）  
**测试目的：** 在进入 FinAgent 1.2.6（Ensemble Promotion & Model Registry）前，验证 1.2.5 已实现的真实数据、Agent 因子发现、Factor Quant v2、多因子 Ensemble、正式统计验证、确定性 replay 和跨 Provider 路径能否作为一个系统稳定协同工作。  
**重要约束：** 本轮系统验收不消费正式 sealed holdout，不执行 live broker，不以“策略是否盈利”作为通过标准。

---

# 1. 测试目标

本轮测试不是重复 GitHub Actions 已完成的单元测试，而是回答以下问题：

1. FinAgent 能否在 Ubuntu 与 Windows 上建立可重复的 Python 测试环境；
2. 真实 Provider 数据能否被规范化为同一 FinAgent 数据契约；
3. 真实数据上的 deterministic baseline 是否可运行；
4. OpenAI Agent 能否生成通过 AST/sandbox 约束的真实因子代码；
5. Factor Quant Engine v2 能否正确计算 IC、RankIC、IC decay、quantile spread、turnover、coverage 与 factor correlation；
6. Agent 是否真正利用 development-only Quant Feedback v2 进行下一轮候选改进；
7. 多轮 discovery 是否完整保留搜索过的 candidate denominator；
8. 多因子 Ensemble 是否以完整 AlphaModel 方式独立拟合与验证，而不是简单加权单因子收益；
9. Formal validation 是否在同一 outer fold 中对 `K 个单因子 + 1 个 Ensemble` 进行 Multiplicity / DSR / PBO / Reality Check；
10. frozen family deterministic replay 是否完全一致；
11. 同一 frozen family 在 Alpaca 与 AKShare 间是否可以做 cross-provider robustness 检查；
12. 当前系统是否达到进入 1.2.6 的 GO 条件。

本轮测试的核心判据是：

```text
系统行为可解释
+ 数据身份可追踪
+ 数值输出有限
+ 搜索 denominator 不漂移
+ replay 可重复
+ provider 差异不被静默吞掉
```

而不是：

```text
Sharpe > 1
或者
Ensemble 必须击败最佳单因子
```

---

# 2. 当前代码基线与测试边界

## 2.1 当前主分支能力

截至基线提交，主链已经具备：

```text
Provider Data
→ ResearchDataset / PIT
→ Agent generated features
→ Factor Quant Feedback v2
→ cumulative Agent discovery
→ complete candidate denominator
→ Factor Ensemble selection
→ GeneratedFeatureEnsembleAlphaModel
→ formal K+1 validation
→ GARCH RiskModel
→ MeanVarianceOptimizer
→ next-open cost-aware execution
→ Multiplicity / DSR / PBO / Reality Check
→ Research governance
```

## 2.2 当前 canonical CLI 的限制

当前 `scripts/run_agent_market_research.py` 仍主要暴露较早的 canonical Agent-market 路径：

```text
LLMMarketFeatureCandidateGenerator
→ GovernedAgentMarketResearchRunner
```

它可以测试：

- 真实 OpenAI API 调用；
- generated feature；
- sandbox；
- nested validation；
- deterministic replay；
- frozen-family cross-provider validation。

但它尚未把 FinAgent 1.2.5 的全部：

```text
AgentFactorQuantDiscoveryLoop
Factor Quant Feedback v2
FactorEnsembleSelector
FactorEnsembleFormalValidator
```

封装为一个单命令 CLI。

因此，本测试计划将测试分成两类：

### A. 可立即通过现有 CLI 执行

- 环境测试；
- 全量 regression；
- Provider 数据拉取；
- 数据质量；
- deterministic market backtest；
- legacy/canonical Agent real-LLM run；
- replay；
- cross-provider validation。

### B. 1.2.5 API 级验收

- Factor Quant v2；
- cumulative Quant Feedback v2；
- Ensemble K+1 formal validation。

当前通过 `pytest` 中的 1.2.5 integration surface 完成。若后续需要让非开发测试人员在真实 Provider 数据上“一条命令”执行完整 1.2.5 workflow，建议另增 cross-platform Python acceptance runner；这属于测试可用性增强，不属于本轮金融逻辑修改。

---

# 3. 操作系统兼容性结论

## 3.1 总体结论

FinAgent **核心 Python 功能没有绑定 Ubuntu 独有能力**。

当前核心依赖：

```text
Python >= 3.11
NumPy
SciPy
SQLite（Python 标准库）
Pathlib
urllib / HTTP clients
OpenAI SDK（可选）
AKShare（可选）
Alpaca SDK（可选）
Tushare（可选）
```

这些能力本身均可在 Windows x64 Python 环境运行。

但是，当前仓库存在三个平台层面的事实：

### 事实 1：环境隔离脚本是 Bash / Ubuntu 语义

以下脚本不能作为原生 Windows PowerShell 的 canonical 入口：

```text
scripts/finagent.sh
scripts/run_tests.sh
scripts/lib/finagent_env.sh
```

它们依赖：

```text
#!/usr/bin/env bash
source
${CONDA_PREFIX}/bin/python
LD_LIBRARY_PATH
/opt/ros
/usr/bin
/bin
```

因此：

- Ubuntu：推荐继续使用这些脚本；
- Windows：不要直接使用这些 `.sh` 文件；
- Windows 测试使用 `conda activate` + `python -m ...`；
- WSL2 可按 Ubuntu 路径测试，但 WSL2 测试不能替代原生 Windows compatibility test。

### 事实 2：CI 当前仅验证 Ubuntu

GitHub Actions 当前使用：

```yaml
runs-on: ubuntu-latest
```

Python matrix 为：

```text
3.11
3.12
3.13
```

因此原生 Windows 在本轮测试前只能称为：

> **Supported by architecture, not yet CI-certified.**

### 事实 3：Windows 必须处理 IANA 时区数据

Provider adapters 使用：

```python
ZoneInfo("Asia/Shanghai")
ZoneInfo("America/New_York")
```

Windows 通常不提供 Python `zoneinfo` 可直接使用的系统 IANA tzdb；所以原生 Windows 测试环境必须安装：

```text
tzdata
```

否则可能在导入 `finagent.data` / provider ingestion 模块时直接出现：

```text
zoneinfo.ZoneInfoNotFoundError
```

本测试计划把 `tzdata` 作为 Windows 必需依赖处理。

---

# 4. 推荐测试环境矩阵

| 环境 | 状态 | 用途 |
|---|---|---|
| Ubuntu 24.04 + Python 3.11 | 主参考环境 | 完整测试 |
| Ubuntu 24.04 + Python 3.12 | CI 对齐 | regression |
| Ubuntu 24.04 + Python 3.13 | CI 对齐 | forward compatibility |
| Windows 11 + Python 3.11 | Windows 主测试环境 | 完整测试 |
| Windows 11 + Python 3.12/3.13 | 可选 | compatibility |
| WSL2 Ubuntu | 可选 | Ubuntu 等价环境，不代表原生 Windows |

建议首次 Windows 验收统一使用 Python 3.11，因为项目的 mypy 和 Conda environment baseline 均以 3.11 为基准。

---

# 5. 测试前冻结规则

测试前必须记录：

```text
Git commit SHA
OS
Python version
Conda environment
Provider
Provider data_version
bars SHA256
LLM model id
research config
```

本轮测试期间：

1. 不修改正式 sealed holdout；
2. 不调用 `consume_sealed_holdout()`；
3. 不以测试结果修改同一份正式 holdout；
4. Agent 测试只使用 development / validation 数据；
5. 不进行 live trading；
6. Paper 测试仅用于 regression，不作为本轮 GO 条件；
7. 所有 Provider credential 仅通过环境变量提供，不写入 Git。

---

# 6. 环境搭建

## 6.1 共用前提

建议将仓库放在较短、无特殊字符的路径。

Ubuntu 示例：

```text
~/workspace/FinAgent
```

Windows 示例：

```text
C:\work\FinAgent
```

Windows 不建议首次测试放在：

```text
C:\Users\<user>\OneDrive\...
```

避免同步软件、路径长度和文件锁影响 SQLite / build 测试。

---

## 6.2 Ubuntu 环境搭建

### Step U-1：Clone

```bash
git clone https://github.com/NewYeYeah/FinAgent.git
cd FinAgent
git checkout main
git pull --ff-only
```

记录：

```bash
git rev-parse HEAD
```

期望基线：

```text
4c4d03e31bdb8978b3c1a52a5614e47818a1935f
```

若主分支已经继续开发，则记录实际 SHA，不要强行回退；测试报告必须注明实际 commit。

### Step U-2：创建 Conda 环境

```bash
conda env create -f environment/environment.yml
conda activate finagent
```

若环境已存在：

```bash
conda env update -n finagent -f environment/environment.yml --prune
conda activate finagent
```

### Step U-3：安装测试所需 optional extras

为了执行 Provider + LLM 测试：

```bash
python -m pip install -e ".[dev,llm-openai,cn-free,us-market,a-share]"
```

### Step U-4：验证 FinAgent 隔离环境

```bash
./scripts/finagent.sh --check
```

期望：

```text
conda env: finagent
Python >= 3.11
ROS paths: none
```

### Step U-5：基础 import smoke

```bash
./scripts/finagent.sh python -c \
'import sys, finagent, numpy, scipy; print(sys.version); print(finagent.__file__)'
```

---

## 6.3 Windows 10/11 原生 PowerShell 环境搭建

> 注意：以下步骤是原生 Windows PowerShell，不是 WSL。

### Step W-1：Clone

PowerShell：

```powershell
git clone https://github.com/NewYeYeah/FinAgent.git
Set-Location FinAgent
git checkout main
git pull --ff-only
git rev-parse HEAD
```

### Step W-2：创建 Conda 环境

```powershell
conda env create -f environment/environment.yml
conda activate finagent
```

若环境已存在：

```powershell
conda env update -n finagent -f environment/environment.yml --prune
conda activate finagent
```

### Step W-3：安装 optional extras

```powershell
python -m pip install -e ".[dev,llm-openai,cn-free,us-market,a-share]"
```

### Step W-4：安装 Windows 必需时区数据库

```powershell
python -m pip install tzdata
```

验证：

```powershell
python -c "from zoneinfo import ZoneInfo; print(ZoneInfo('America/New_York')); print(ZoneInfo('Asia/Shanghai'))"
```

必须正常输出两个时区名称。

### Step W-5：建立与 Ubuntu 类似的 Python 隔离语义

`scripts/finagent.sh` 不适用于原生 Windows。

PowerShell 中执行：

```powershell
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
$env:PYTHONNOUSERSITE = "1"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
$env:PYTHONUTF8 = "1"
```

检查解释器：

```powershell
python -c "import sys; print(sys.executable); print(sys.version)"
```

期望 `sys.executable` 位于当前 Conda 环境，例如：

```text
...\envs\finagent\python.exe
```

### Step W-6：基础 import smoke

```powershell
python -c "import finagent, numpy, scipy; print(finagent.__file__)"
python -c "from finagent.data import AlpacaMarketDataIngestor, AKShareMarketDataIngestor; print('provider imports ok')"
```

### Windows 明确禁止/不推荐

原生 PowerShell 下不要执行：

```text
./scripts/finagent.sh
./scripts/run_tests.sh
source scripts/lib/finagent_env.sh
```

也不建议为了“能执行 .sh”而用 Git Bash 强行运行 `finagent_env.sh`，因为该脚本包含 Unix Conda 路径与系统 PATH 假设。

若使用 WSL2，则应完全按照 Ubuntu 测试步骤执行，并把测试环境记录为：

```text
WSL2 Ubuntu
```

而不是：

```text
Windows native
```

---

# 7. Credential 配置

## 7.1 Alpaca

Ubuntu：

```bash
export ALPACA_API_KEY='...'
export ALPACA_SECRET_KEY='...'
```

Windows PowerShell：

```powershell
$env:ALPACA_API_KEY = "..."
$env:ALPACA_SECRET_KEY = "..."
```

## 7.2 OpenAI

Ubuntu：

```bash
export OPENAI_API_KEY='...'
```

Windows：

```powershell
$env:OPENAI_API_KEY = "..."
```

## 7.3 HiThink（可选）

Ubuntu：

```bash
export HITHINK_FINANCE_API_KEY='...'
```

Windows：

```powershell
$env:HITHINK_FINANCE_API_KEY = "..."
```

## 7.4 Tushare（可选）

Ubuntu：

```bash
export TUSHARE_TOKEN='...'
```

Windows：

```powershell
$env:TUSHARE_TOKEN = "..."
```

禁止：

- 把 token 写入 TOML；
- 把 `.env` 提交 Git；
- 把 credential 写入测试报告。

---

# 8. 测试阶段总览

| ID | 测试 | 数据 | LLM | 必须通过 |
|---|---|---|---|---|
| T0 | Baseline / regression | synthetic | 否 | 是 |
| T1 | Windows/Ubuntu platform smoke | 无/fixture | 否 | 是 |
| T2 | Provider ingestion | real | 否 | 是 |
| T3 | Data quality / provider diff | real | 否 | 是 |
| T4 | Deterministic market baseline | real | 否 | 是 |
| T5 | Canonical real-LLM Agent research | real | 是 | 是，若配置 LLM |
| T6 | Factor Quant v2 / Feedback v2 regression | synthetic/in-memory | test provider | 是 |
| T7 | Ensemble K+1 formal validation | synthetic/in-memory | 否 | 是 |
| T8 | Deterministic replay | real | 否 | 是 |
| T9 | Frozen-family cross-provider | real | 否 | P1，建议通过 |
| T10 | Paper/promotion regression | synthetic | 否 | 非本轮 GO 硬门槛 |

---

# 9. T0 — Baseline Regression

## 9.1 Ubuntu

```bash
./scripts/run_tests.sh -q
```

Coverage：

```bash
./scripts/run_tests.sh \
  --cov=finagent \
  --cov-report=term \
  --cov-fail-under=50
```

静态检查：

```bash
./scripts/finagent.sh ruff check src tests scripts --select E9,F63,F7,F82
./scripts/finagent.sh mypy \
  src/finagent/domain/metrics.py \
  src/finagent/domain/trading.py \
  src/finagent/domain/universe.py \
  src/finagent/research/programs.py \
  src/finagent/models/alpha/primitives.py \
  src/finagent/models/alpha/generated.py \
  src/finagent/research/agent_market.py \
  src/finagent/research/market_validation.py \
  src/finagent/services/portfolio.py \
  src/finagent/data/ingestion \
  src/finagent/backtest/market_study.py
./scripts/finagent.sh python -m build
./scripts/finagent.sh python -m pip check
```

## 9.2 Windows PowerShell

如果已经设置：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
```

普通测试：

```powershell
python -m pytest -q
```

Coverage 必须显式加载 pytest-cov：

```powershell
python -m pytest -p pytest_cov.plugin --cov=finagent --cov-report=term --cov-fail-under=50
```

静态检查：

```powershell
ruff check src tests scripts --select E9,F63,F7,F82
mypy src/finagent/domain/metrics.py src/finagent/domain/trading.py src/finagent/domain/universe.py src/finagent/research/programs.py src/finagent/models/alpha/primitives.py src/finagent/models/alpha/generated.py src/finagent/research/agent_market.py src/finagent/research/market_validation.py src/finagent/services/portfolio.py src/finagent/data/ingestion src/finagent/backtest/market_study.py
python -m build
python -m pip check
```

## 9.3 通过标准

必须：

```text
pytest exit code = 0
coverage >= 50%
ruff critical = PASS
mypy selected surface = PASS
build = PASS
pip check = PASS
```

Windows 若只出现 `.sh` 相关失败，不视为 Python core failure；但必须记录为 platform wrapper incompatibility。

---

# 10. T1 — Platform / Timezone / SQLite Smoke

## 10.1 时区

Ubuntu：

```bash
./scripts/finagent.sh python - <<'PY'
from zoneinfo import ZoneInfo
print(ZoneInfo("Asia/Shanghai"))
print(ZoneInfo("America/New_York"))
PY
```

Windows：

```powershell
python -c "from zoneinfo import ZoneInfo; print(ZoneInfo('Asia/Shanghai')); print(ZoneInfo('America/New_York'))"
```

通过标准：无 `ZoneInfoNotFoundError`。

## 10.2 SQLite

Ubuntu：

```bash
./scripts/finagent.sh python -c 'import sqlite3; print(sqlite3.sqlite_version)'
```

Windows：

```powershell
python -c "import sqlite3; print(sqlite3.sqlite_version)"
```

通过标准：可正常 import，并输出 SQLite version。

## 10.3 Pathlib

Windows 必须确认：

```powershell
python -c "from pathlib import Path; p=Path('reports/test.txt').resolve(); print(p); print(p.as_uri())"
```

通过标准：Windows 路径和 URI 均能生成。

---

# 11. T2 — Alpaca 真实数据拉取

Alpaca 作为 US primary Provider，建议作为系统验收主数据源。

当前配置：

```text
configs/markets/us_etf_agent_data_alpaca.toml
```

Universe：

```text
SPY
QQQ
IWM
DIA
```

Feed：

```text
IEX
```

## 11.1 Ubuntu

```bash
./scripts/finagent.sh python scripts/pull_market_data.py \
  configs/markets/us_etf_agent_data_alpaca.toml \
  --show-capabilities
```

## 11.2 Windows

```powershell
python scripts/pull_market_data.py configs/markets/us_etf_agent_data_alpaca.toml --show-capabilities
```

## 11.3 预期产物

```text
data/market/us_etf_alpaca/raw.jsonl
data/market/us_etf_alpaca/bars.csv
data/market/us_etf_alpaca/manifest.json
```

具体文件以 `MaterializedMarketData` 实际输出为准。

## 11.4 必查字段

Manifest 至少检查：

```text
provider == alpaca
quality_passed == true
request.market == us_equity
request.symbols 包含 SPY/QQQ/IWM/DIA
normalized_sha256 非空
data_version 非空
```

不得因为 Provider 请求失败自动 fallback 到 AKShare。

---

# 12. T3 — Market Data Quality

## 12.1 Alpaca bars validation

Ubuntu：

```bash
./scripts/finagent.sh python scripts/validate_market_data.py \
  data/market/us_etf_alpaca/bars.csv \
  --expected-symbol SPY \
  --expected-symbol QQQ \
  --expected-symbol IWM \
  --expected-symbol DIA \
  --report reports/us_etf_alpaca_quality.json
```

Windows：

```powershell
python scripts/validate_market_data.py data/market/us_etf_alpaca/bars.csv `
  --expected-symbol SPY `
  --expected-symbol QQQ `
  --expected-symbol IWM `
  --expected-symbol DIA `
  --report reports/us_etf_alpaca_quality.json
```

PowerShell 也可以写为单行。

通过：

```text
passed == true
exit code == 0
```

重点人工检查：

```text
missing rows
duplicate rows
OHLC validity
calendar consistency
symbol completeness
```

---

# 13. T3-B — AKShare Secondary Dataset

## 13.1 安装

如果尚未安装：

```text
pip install -e ".[cn-free]"
```

## 13.2 拉取

Ubuntu：

```bash
./scripts/finagent.sh python scripts/pull_market_data.py \
  configs/markets/us_etf_agent_data_akshare.toml \
  --show-capabilities
```

Windows：

```powershell
python scripts/pull_market_data.py configs/markets/us_etf_agent_data_akshare.toml --show-capabilities
```

AKShare 属于 free/best-effort QA Provider，网络端点变化导致拉取失败时应记录为 Provider availability issue，不应通过修改 FinAgent 研究规则规避。

---

# 14. T3-C — Cross-provider Diff

假设：

```text
left  = Alpaca
right = AKShare
```

Ubuntu：

```bash
./scripts/finagent.sh python scripts/compare_market_providers.py \
  data/market/us_etf_alpaca/bars.csv \
  data/market/us_etf_akshare/bars.csv \
  --left-provider alpaca \
  --right-provider akshare \
  --output reports/us_etf_provider_diff.json
```

Windows：

```powershell
python scripts/compare_market_providers.py `
  data/market/us_etf_alpaca/bars.csv `
  data/market/us_etf_akshare/bars.csv `
  --left-provider alpaca `
  --right-provider akshare `
  --output reports/us_etf_provider_diff.json
```

这里不要求：

```text
所有数据完全相同
```

必须确认：

```text
差异被显式报告
Provider identity 保留
没有 silent reconciliation
```

重点检查：

```text
calendar mismatch
close absolute/relative difference
volume difference
```

---

# 15. T4 — Deterministic Market Baseline

在引入 LLM 前，必须确认真实数据可以通过 deterministic quant baseline。

推荐：

```text
configs/markets/us_etf_smoke.toml
```

Ubuntu：

```bash
./scripts/finagent.sh python scripts/run_market_backtest.py \
  configs/markets/us_etf_smoke.toml \
  --bars data/market/us_etf_alpaca/bars.csv \
  --manifest data/market/us_etf_alpaca/manifest.json \
  --report reports/us_etf_deterministic_baseline.json
```

Windows：

```powershell
python scripts/run_market_backtest.py `
  configs/markets/us_etf_smoke.toml `
  --bars data/market/us_etf_alpaca/bars.csv `
  --manifest data/market/us_etf_alpaca/manifest.json `
  --report reports/us_etf_deterministic_baseline.json
```

通过标准：

- 所有 nested folds 完成；
- 所有 metric 为有限值；
- next-open execution 正常；
- cost scenarios 正常；
- 无 digest mismatch；
- 无 manifest quality failure。

本测试不要求策略盈利。

---

# 16. T5 — Canonical Real-LLM Agent Research

当前 canonical CLI 可以验证真实 OpenAI 生成因子和旧版 Agent-market 主线的稳定性。

## 16.1 创建本地 config

不要直接修改仓库 tracked config。

Ubuntu：

```bash
cp configs/markets/us_etf_agent_research.toml \
   configs/markets/us_etf_agent_research.local.toml
```

Windows：

```powershell
Copy-Item configs/markets/us_etf_agent_research.toml configs/markets/us_etf_agent_research.local.toml
```

编辑：

```toml
llm_model = "<当前 OpenAI API 账户可用模型 ID>"
```

首次生成测试还建议为每次 fresh-LLM run 使用独立的本地研究身份与 state 目录，例如：

```toml
task_id = "us-etf-agent-research-acceptance-01"
program_id = "us-etf-agent-program-acceptance-01"
family_id = "us-etf-agent-family-acceptance-01"
state_dir = ".finagent/agent-market-us-acceptance-01"
report_path = "reports/us_etf_agent_real_llm_run01.json"
```

原因：fresh LLM run 是新的搜索，不应把新候选写入旧的 frozen family / program identity。随后做 deterministic replay 时必须继续使用这一份相同 local config 与 state directory。

本地 config 不应提交 Git。

## 16.2 运行

Ubuntu：

```bash
./scripts/finagent.sh python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.local.toml \
  --bars data/market/us_etf_alpaca/bars.csv \
  --manifest data/market/us_etf_alpaca/manifest.json \
  --report reports/us_etf_agent_real_llm_run01.json
```

Windows：

```powershell
python scripts/run_agent_market_research.py `
  configs/markets/us_etf_agent_research.local.toml `
  --bars data/market/us_etf_alpaca/bars.csv `
  --manifest data/market/us_etf_alpaca/manifest.json `
  --report reports/us_etf_agent_real_llm_run01.json
```

## 16.3 记录指标

记录：

```text
requested candidates
valid generated candidates
AST failures
sandbox failures
lookback violations
missing field failures
candidate digests
LLM model id
token usage（若 report 中可得）
```

GenerationSuccessRate：

```text
valid generated candidates / requested candidates
```

此测试目的是验证 Agent 生成链，不要求 generated factor 被统计接受。

---

# 17. T6 — FinAgent 1.2.5 Factor Quant / Feedback v2 Regression

由于当前 1.2.5 Quant workflow 尚未提供单独 canonical CLI，本轮必须执行其正式 integration tests。

Ubuntu：

```bash
./scripts/run_tests.sh -q \
  tests/test_agent_factor_discovery_v123.py \
  tests/test_agent_factor_workflow_v123.py \
  tests/test_ensemble_validation_feedback_v125.py
```

Windows：

```powershell
python -m pytest -q `
  tests/test_agent_factor_discovery_v123.py `
  tests/test_agent_factor_workflow_v123.py `
  tests/test_ensemble_validation_feedback_v125.py
```

也可以使用：

```powershell
python -m pytest -q -k "factor or ensemble"
```

但正式测试报告建议记录明确文件列表。

## 17.1 必须验证的 Factor Quant 指标

至少覆盖：

```text
Pearson IC
RankIC
ICIR
multi-horizon IC
quantile mean return
quantile monotonicity
Q-high - Q-low spread
long-short Sharpe
turnover
coverage
factor-value correlation
```

## 17.2 Metamorphic sanity checks

建议人工/附加测试构造：

```text
F1 = simple_return_5
F2 = -simple_return_5
F3 = 0.8 * simple_return_5
```

期望：

```text
IC(F2) ≈ -IC(F1)
RankIC(F2) ≈ -RankIC(F1)
Corr_rank(F1, F3) ≈ 1
```

若上述关系明显不成立，应优先检查 Quant Engine，不进入 1.2.6。

---

# 18. T7 — Quant Feedback v2 行为测试

必须确认 Agent feedback 只含 development evidence。

允许字段包括：

```text
RankIC / ICIR
IC decay
quantile monotonicity
long-short spread
long-short Sharpe
turnover
coverage
factor correlation
```

不允许：

```text
outer_metrics
sealed holdout metrics
promotion result
paper result
live result
```

需要检查第二轮 Agent 输入是否出现：

```text
DEVELOPMENT-ONLY FACTOR QUANT FEEDBACK V2
```

并确认第二轮 cumulative report 包含：

```text
Round 1 candidates
+
Round 2 candidates
```

而不是只分析最新 round。

### 人工评估 Agent 是否真的利用 feedback

例如 Round 1：

```text
RankIC 高
turnover 极高
1d IC 明显高于 3d IC
```

合理的下一轮研究方向应趋向：

```text
降低换手
避免快速翻转
调整 horizon
寻找互补因子
```

如果 Agent 只是生成：

```text
0.9 * old_factor
```

即使代码测试通过，也应在测试报告标记：

```text
Agent feedback effectiveness = WEAK
```

这属于研究质量问题，不是程序崩溃问题。

---

# 19. T8 — Ensemble K+1 Formal Validation

正式 denominator：

```text
K 个单因子
+
1 个 frozen ensemble
```

因此：

```text
N_trials = K + 1
```

必须检查：

1. Ensemble 不是单因子 return 序列线性相加；
2. 每个 outer fold 都重新 fit 单因子模型和 ensemble AlphaModel；
3. 所有 trial 使用同一 fold chronology；
4. 所有 trial 使用同一 risk / optimizer / execution / cost contract；
5. Multiplicity 计算使用 `K+1` denominator；
6. DSR 的 `n_trials == K+1`；
7. PBO 使用对齐的 OOS return matrix；
8. Reality Check 使用同一矩阵；
9. Ensemble 与 best-single 进行 paired incremental comparison。

测试命令已包含在 T6 的：

```text
tests/test_ensemble_validation_feedback_v125.py
```

### 通过标准

不要求：

```text
Ensemble Sharpe > Best Single Sharpe
```

要求：

```text
如果 Ensemble 输，系统正确报告输；
如果 Ensemble 赢，统计证据与 denominator 可解释。
```

---

# 20. T9 — Deterministic Frozen-Family Replay

以 T5 生成的 report 为 reference。

Ubuntu：

```bash
./scripts/finagent.sh python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.local.toml \
  --bars data/market/us_etf_alpaca/bars.csv \
  --manifest data/market/us_etf_alpaca/manifest.json \
  --frozen-family-report reports/us_etf_agent_real_llm_run01.json \
  --assert-replay \
  --report reports/us_etf_agent_real_llm_replay.json
```

Windows：

```powershell
python scripts/run_agent_market_research.py `
  configs/markets/us_etf_agent_research.local.toml `
  --bars data/market/us_etf_alpaca/bars.csv `
  --manifest data/market/us_etf_alpaca/manifest.json `
  --frozen-family-report reports/us_etf_agent_real_llm_run01.json `
  --assert-replay `
  --report reports/us_etf_agent_real_llm_replay.json
```

Replay 模式不应再次调用 LLM。

必须一致：

```text
candidate digests
fold chronology
selection
acceptance
aggregate metrics
result identity（按当前 replay policy）
```

若 replay 失败：

```text
NO-GO 1.2.6
```

---

# 21. T9-B — Replay Validation CLI

Ubuntu：

```bash
./scripts/finagent.sh python scripts/validate_agent_market_research.py \
  reports/us_etf_agent_real_llm_run01.json \
  reports/us_etf_agent_real_llm_replay.json \
  --mode replay \
  --output reports/us_etf_agent_replay_validation.json
```

Windows：

```powershell
python scripts/validate_agent_market_research.py `
  reports/us_etf_agent_real_llm_run01.json `
  reports/us_etf_agent_real_llm_replay.json `
  --mode replay `
  --output reports/us_etf_agent_replay_validation.json
```

期望：

```text
passed == true
exit code == 0
```

---

# 22. T10 — Frozen-Family Cross-provider Validation

这里必须使用：

```text
同一 frozen family
```

不得：

```text
Alpaca 上搜索一遍
AKShare 上重新让 Agent 搜索一遍
```

推荐流程：

```text
Alpaca Agent search
      ↓
frozen family
      ├── Alpaca run
      └── AKShare run
```

AKShare run 继续使用 T5 的同一 local config、同一 task/program/family/state identity，只通过 CLI 显式覆盖 bars / manifest / provider，因此不会重新调用 LLM：

## Ubuntu

```bash
./scripts/finagent.sh python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.local.toml \
  --bars data/market/us_etf_akshare/bars.csv \
  --manifest data/market/us_etf_akshare/manifest.json \
  --provider akshare \
  --frozen-family-report reports/us_etf_agent_real_llm_run01.json \
  --report reports/us_etf_agent_market_research_akshare.json
```

## Windows PowerShell

```powershell
python scripts/run_agent_market_research.py `
  configs/markets/us_etf_agent_research.local.toml `
  --bars data/market/us_etf_akshare/bars.csv `
  --manifest data/market/us_etf_akshare/manifest.json `
  --provider akshare `
  --frozen-family-report reports/us_etf_agent_real_llm_run01.json `
  --report reports/us_etf_agent_market_research_akshare.json
```

然后比较两份 research result：

## Ubuntu

```bash
./scripts/finagent.sh python scripts/validate_agent_market_research.py \
  reports/us_etf_agent_real_llm_run01.json \
  reports/us_etf_agent_market_research_akshare.json \
  --mode cross_provider \
  --left-bars data/market/us_etf_alpaca/bars.csv \
  --right-bars data/market/us_etf_akshare/bars.csv \
  --output reports/us_etf_agent_cross_provider_validation.json \
  --store .finagent/agent-market-us-acceptance-01/agent_market_validation.sqlite
```

## Windows PowerShell

```powershell
python scripts/validate_agent_market_research.py `
  reports/us_etf_agent_real_llm_run01.json `
  reports/us_etf_agent_market_research_akshare.json `
  --mode cross_provider `
  --left-bars data/market/us_etf_alpaca/bars.csv `
  --right-bars data/market/us_etf_akshare/bars.csv `
  --output reports/us_etf_agent_cross_provider_validation.json `
  --store .finagent/agent-market-us-acceptance-01/agent_market_validation.sqlite
```

Cross-provider validation 要求 normalized calendar 对齐。重点比较：

```text
selection agreement
acceptance agreement
aggregate metric differences
provider data diff
```

可选预注册阈值示例：

```text
--min-selection-agreement 0.75
--min-acceptance-agreement 0.75
--metric-abs-limit sharpe=0.25
--metric-abs-limit max_drawdown=0.05
```

如果研究协议没有事前定义阈值，不要为了让测试“通过”而在看到结果后临时设置宽松阈值。

这一步的目标是 robustness，不要求 Alpaca 与 AKShare 完全一致。

---

# 23. T11 — Paper / Promotion Regression（非本轮硬门槛）

为了确认 1.2.3–1.2.5 没有破坏既有 promotion/paper 模块，建议执行：

Ubuntu：

```bash
./scripts/run_tests.sh -q -k "promotion or paper or sealed_holdout"
```

Windows：

```powershell
python -m pytest -q -k "promotion or paper or sealed_holdout"
```

本轮不执行真实 broker，也不消费正式 sealed holdout。

---

# 24. Windows 专项测试

Windows 验收必须额外记录以下项目。

## W-A：ZoneInfo

```text
PASS / FAIL
```

## W-B：Native PowerShell pytest

必须直接在 PowerShell 中运行：

```powershell
python -m pytest -q
```

不能仅以 WSL 结果代替。

## W-C：SQLite writable

确认：

- `tests` 可创建临时 SQLite；
- `.finagent/` 下 store 可创建；
- 没有 Windows file lock 导致的异常。

## W-D：Provider network

至少 Alpaca 或 AKShare 一个真实 Provider 拉取成功。

## W-E：Path handling

确认：

```text
reports\...
data\market\...
SQLite paths
Path.as_uri()
```

不出现硬编码 `/tmp` 或 `/home/...` 依赖。

## W-F：Build

```powershell
python -m build
python -m pip check
```

通过。

---

# 25. Ubuntu 专项测试

Ubuntu 额外确认环境隔离器：

```bash
./scripts/finagent.sh --check
```

如果测试机装有 ROS2，则建议从曾经 source ROS2 的 shell 中执行：

```bash
source /opt/ros/<distro>/setup.bash
./scripts/finagent.sh --check
```

FinAgent isolated shell 仍应报告：

```text
ROS paths: none
```

确保 ROS/colcon 环境不会污染量化项目。

---

# 26. 测试结果记录模板

## 26.1 环境

```text
Tester:
Date:
OS:
OS Version:
Native / WSL:
Python:
Conda:
Git SHA:
FinAgent branch:
```

## 26.2 Provider

```text
Primary Provider:
Secondary Provider:
Feed:
Dataset start:
Dataset end:
Symbols:
Data version:
Normalized SHA256:
```

## 26.3 LLM

```text
Provider: OpenAI
Model:
Requested candidates:
Valid candidates:
Generation failures:
Sandbox failures:
```

不要写 API key。

## 26.4 Factor Quant

```text
Candidate count:
Mean/median RankIC:
IC decay observations:
Highest turnover:
Lowest coverage:
Highest |factor correlation|:
Selected ensemble components:
Ensemble weights:
```

## 26.5 Formal Validation

```text
K single trials:
Ensemble trials: 1
Total denominator: K+1
Best single:
Best single Sharpe:
Ensemble Sharpe:
Ensemble - best-single mean return:
Paired p-value:
DSR:
PBO:
Reality Check:
```

## 26.6 Replay

```text
Replay passed:
Digest mismatch:
Fold mismatch:
Metric mismatch:
```

## 26.7 Cross-provider

```text
Calendar mismatch:
Selection agreement:
Acceptance agreement:
Metric drift:
Unexplained discrepancy:
```

---

# 27. 缺陷分级

## P0 — 阻塞 1.2.6

包括：

```text
future information enters feature formation
PIT failure
development/validation chronology wrong
candidate denominator drift
formal K+1 denominator wrong
replay non-deterministic
same input produces inconsistent strategy identity
NaN/Inf reaches accepted research result
Ensemble bypasses frozen weights
Provider silently changes
Windows core Python test cannot run due Linux-only import/system call
```

## P1 — 记录并允许继续

包括：

```text
AKShare temporary endpoint failure
minor provider value discrepancy
Windows shell wrapper unavailable
cross-database crash recovery edge case
Agent generated factor quality weak
Agent duplicate factor rate high
```

但如果某 P1 大面积影响测试可执行性，应升级 P0。

## P2 — 后续 hardening

```text
physical data isolation
cryptographic sealing
distributed recovery
Windows-specific convenience launchers
full multi-OS CI optimization
```

---

# 28. 进入 1.2.6 的 GO / NO-GO 标准

## GO

至少满足：

- [ ] Ubuntu 全量 pytest 通过；
- [ ] Windows 原生 Python 全量 pytest 通过；
- [ ] Windows ZoneInfo/tzdata smoke 通过；
- [ ] Ruff critical / build / pip check 通过；
- [ ] Alpaca real data pull 通过；
- [ ] market data validation 通过；
- [ ] deterministic market baseline 完成；
- [ ] 至少一次 real OpenAI Agent generation 成功；
- [ ] generated feature sandbox 正常；
- [ ] Factor Quant v2 integration tests 通过；
- [ ] Quant Feedback v2 cumulative behavior 通过；
- [ ] K+1 Ensemble formal validation 通过；
- [ ] 所有正式 validation metrics 为有限值；
- [ ] deterministic replay 完全通过；
- [ ] 无 P0 缺陷；
- [ ] sealed holdout 未被本轮测试消费。

Cross-provider validation 建议完成，但若 AKShare 因临时上游 API 故障无法测试，可作为 P1 记录；不能因此修改 Alpaca 主研究结果。

## NO-GO

任一情况发生：

```text
PIT chronology violation
replay failure
formal denominator drift
ensemble selection/reconstruction identity mismatch
Windows core import failure且无法通过明确依赖修复
real market data manifest/digest inconsistency
outer/holdout evidence进入 Agent feedback
统计结果出现未处理 NaN/Inf
```

则暂停 1.2.6，先修正当前层。

---

# 29. Windows 支持状态的最终判定规则

当前建议项目状态写为：

```text
Ubuntu: primary / CI-certified development environment
Windows: supported test environment, pending CI certification
WSL2: Ubuntu-compatible convenience environment
```

当以下条件完成后，可把 Windows 升级为正式 CI-supported：

1. `tzdata` 加入跨平台依赖或 Windows extra；
2. 增加 GitHub Actions `windows-latest` job；
3. Windows native pytest 全绿；
4. 至少一个 Provider real-data smoke 在 Windows 完成；
5. build / pip check 在 Windows 完成。

不建议为了 Windows 支持改写金融核心代码。当前主要差异属于：

```text
environment launcher
IANA timezone dependency
CI runner
shell syntax
```

而不是：

```text
AlphaModel
RiskModel
ResearchDataset
Factor Quant
Agent
SQLite governance
backtest
```

---

# 30. 本轮测试后的下一步

若 GO：

```text
FinAgent 1.2.5 System Acceptance
        ↓
GO
        ↓
FinAgent 1.2.6
Ensemble Promotion & Model Registry
        ↓
Sealed Holdout
        ↓
Promotion
        ↓
Registered Ensemble Model
        ↓
PAPER
```

若 NO-GO：

```text
记录 P0
↓
针对当前层修复
↓
重复失败测试
↓
全量 regression
↓
重新做 GO / NO-GO
```

不要因为测试失败直接放宽：

```text
PIT
multiplicity
DSR/PBO
candidate denominator
replay identity
```

等规则。

---

# 31. 推荐测试执行顺序（简版）

```text
1. 环境与 commit 冻结
2. T0 全量 regression
3. T1 Windows/Ubuntu platform smoke
4. T2 Alpaca real-data pull
5. T3 data quality
6. T4 deterministic baseline
7. T5 real OpenAI Agent run
8. T6 Factor Quant / Feedback v2 regression
9. T7 K+1 ensemble validation
10. T8 deterministic replay
11. T9 cross-provider validation
12. GO / NO-GO review
13. GO 后开始 1.2.6
```

本轮**不要提前消费正式 sealed holdout**。
