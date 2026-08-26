# FinAgent 1.2.5 系统验收测试计划

**文档版本：** v1.2  
**修订日期：** 2026-08-26  
**适用代码基线：** FinAgent 1.2.5 acceptance surface  
**基线分支：** `main`  
**测试时必须记录：** `git rev-parse HEAD` 的实际提交  
**适用系统：** Ubuntu 22.04/24.04、Windows 10/11 x64 原生 PowerShell  
**LLM 主路径：** DeepSeek 官方 DeepSeek-V4-Pro  
**LLM 兼容路径：** 硅基流动 DeepSeek-V4-Pro、OpenAI Responses API  
**市场数据主路径：** Alpaca US daily data；AKShare cross-provider validation  
**重要约束：** 本轮验收不消费正式 sealed holdout，不执行 live broker，不以“策略是否盈利”作为通过标准。

---

# 1. 本轮修订重点

v1.2 对此前测试计划补充两个缺失的工程边界。

第一，**市场数据 API credential 与 LLM API credential 采用同类封装**：

```text
tracked public profile
        ↓
host-side config/factory
        ↓
repository-external secret store
        ↓
provider SDK/client
        ↓
normalized market data
```

Canonical market-data CLI 不再要求测试人员手动设置：

```text
ALPACA_API_KEY
ALPACA_SECRET_KEY
TUSHARE_TOKEN
HITHINK_FINANCE_API_KEY
```

这些旧环境变量入口可以作为底层 adapter 的兼容接口继续存在，但**不再是 1.2.5 canonical test path**。

第二，**Ubuntu shell 与 Windows PowerShell 的命令续行符必须明确区分**：

```text
Ubuntu / bash       : \
Windows PowerShell  : `
```

PowerShell 的反引号 `` ` `` 必须是该行最后一个有效字符，**后面不能有空格**。不要在原生 PowerShell 中复制 bash 的 `\` 续行语法。

---

# 2. 测试目标

本轮系统验收回答以下问题：

1. FinAgent 能否在 Ubuntu 与原生 Windows 上建立可重复环境；
2. LLM 与市场数据 Provider 是否都能通过 public profile 进行切换；
3. DeepSeek 官方 V4-Pro 是否能作为 canonical LLM；
4. 硅基流动 DeepSeek V4-Pro 是否能作为第二 LLM 路径；
5. OpenAI provider 是否保持可选兼容；
6. Alpaca credential 是否不再依赖 shell 环境变量逐项配置；
7. LLM/API key 与 market-data credential 是否都与 Agent prompt、metadata、report、audit 隔离；
8. Alpaca / AKShare 等真实数据能否稳定落入同一 FinAgent 数据契约；
9. deterministic market baseline 是否可重复；
10. Factor Quant Engine v2、Quant Feedback v2、完整 candidate denominator 是否正常；
11. 多因子 Ensemble 是否以完整 AlphaModel 方式拟合与验证；
12. `K single factors + 1 ensemble` 是否进入同一正式统计治理面；
13. frozen-family replay 是否在完全没有 LLM credential 时仍可执行；
14. 同一 frozen family 是否可做 Alpaca / AKShare cross-provider robustness；
15. 当前系统是否达到进入 1.2.6 的 GO 条件。

核心判据：

```text
系统行为可解释
+ 数据身份可追踪
+ LLM provider 可替换
+ market-data provider 可替换
+ credential 不进入模型上下文
+ 数值输出有限
+ candidate denominator 不漂移
+ replay 可重复且不依赖 LLM
+ provider 差异不被静默吞掉
```

以下不是验收标准：

```text
Sharpe > 1
Ensemble 必须击败最佳单因子
不同 LLM 必须生成相同因子
```

---

# 3. Provider 配置架构

## 3.1 LLM public profiles

公共配置：

```text
configs/llm.toml
```

当前 profiles：

| Profile | Provider | Model/API | 角色 |
|---|---|---|---|
| `deepseek_official_v4_pro` | DeepSeek 官方 | `deepseek-v4-pro` / Chat Completions | **主力 / 必测** |
| `siliconflow_deepseek_v4_pro` | 硅基流动 | `deepseek-ai/DeepSeek-V4-Pro` / Chat Completions | 第三方路径 / 必测接口 |
| `openai` | OpenAI | 测试账户可用模型 / Responses API | 可选兼容 |

Canonical research config：

```toml
llm_config_path = "configs/llm.toml"
llm_profile = "deepseek_official_v4_pro"
```

## 3.2 Market-data public profiles

公共配置：

```text
configs/market_data.toml
```

当前 profiles：

| Profile | Provider | Credential alias | 角色 |
|---|---|---|---|
| `alpaca_primary` | Alpaca | `alpaca` | US primary / 必测 |
| `akshare_free` | AKShare | 无 | 免费 secondary / cross-provider |
| `tushare_optional` | Tushare | `tushare` | A-share optional |
| `hithink_official` | HiThink | `hithink` | A-share official daily candidate |

Market study config 显式绑定 public profile，例如：

```toml
[market]
provider = "alpaca"
market_data_config_path = "configs/market_data.toml"
market_data_profile = "alpaca_primary"
```

`pull_market_data.py` 会检查：

```text
market.provider == selected market-data profile provider
```

不允许配置写 `provider = "alpaca"`，却静默用另一个 profile。

## 3.3 统一 host-side secret store

LLM 与收费市场数据 Provider 共用一个仓库外 secret store：

```text
~/.config/finagent/secrets.toml
```

Canonical 模板：

```text
configs/secrets.example.toml
```

历史模板：

```text
configs/llm-secrets.example.toml
```

继续保留兼容，但新环境优先使用 `configs/secrets.example.toml`。

真实 secret 文件结构：

```toml
[api_keys]
deepseek_official = "<DeepSeek key>"
siliconflow = "<SiliconFlow key>"
openai = "<optional OpenAI key>"

[market_credentials.alpaca]
api_key = "<Alpaca API key>"
secret_key = "<Alpaca secret key>"

[market_credentials.tushare]
token = "<optional Tushare token>"

[market_credentials.hithink]
api_key = "<optional HiThink key>"
```

只填写本轮实际需要测试的 Provider。

---

# 4. Credential 安全边界

## 4.1 LLM

`LLMProfile` 只能包含：

```text
provider
model
base_url
secret_id
公开推理参数
```

不能包含真实 key。

真实 key 只在 host-side loader 构造 SDK client 时读取，不进入：

```text
LLMRequest
AgentTask.metadata
prompt
system message
research report
SQLite Agent/LLM audit payload
```

## 4.2 Market data

`MarketDataProfile` 只能包含：

```text
profile name
provider
secret_id
```

public profile 中若直接写入：

```text
api_key
secret_key
token
password
api_secret
```

loader 必须 fail closed。

收费数据 Provider 的 credential 只用于 host-side SDK/client 构造，不进入：

```text
MarketDataPullRequest.metadata
manifest
normalized bars
Agent task
LLM prompt
research report
```

AKShare 不需要 credential，选择 `akshare_free` 时不得读取 secret 文件。

## 4.3 Secret 文件权限

POSIX 默认要求：

```text
0600
```

Windows 当前不使用 POSIX mode-bit 检查，但 secret 文件必须位于用户私有目录，且不得放进 Agent 可读 workspace 或 Git 仓库。

环境变量：

```text
FINAGENT_SECRETS_FILE
```

只允许覆盖**secret 文件路径**，不用于直接存放 key。

---

# 5. Shell 语法约定

## 5.1 Ubuntu / bash

多行命令使用反斜杠：

```bash
python some_script.py \
  first_argument \
  --option value
```

## 5.2 Windows PowerShell

多行命令使用反引号：

```powershell
python some_script.py `
  first_argument `
  --option value
```

注意：

1. `` ` `` 必须位于行尾；
2. `` ` `` 后不能再有空格或注释；
3. bash 的 `\` 在 PowerShell 中不是续行符；
4. 文档中的 `bash` block 不得直接复制到原生 PowerShell；
5. Python 自身可以识别 `/` 路径，但本文 Windows 示例优先使用 `\` 以减少歧义。

---

# 6. 环境安装

## 6.1 Ubuntu

```bash
git clone https://github.com/NewYeYeah/FinAgent.git
cd FinAgent
conda env create -f environment/environment.yml
conda activate finagent
python -m pip install -e ".[dev,llm,cn-free,us-market,a-share]"
```

已有环境：

```bash
conda env update -n finagent -f environment/environment.yml --prune
conda activate finagent
python -m pip install -e ".[dev,llm,cn-free,us-market,a-share]"
```

## 6.2 Windows PowerShell

```powershell
git clone https://github.com/NewYeYeah/FinAgent.git
Set-Location FinAgent
conda env create -f environment\environment.yml
conda activate finagent
python -m pip install -e ".[dev,llm,cn-free,us-market,a-share]"
python -m pip install tzdata
```

验证时区：

```powershell
python -c "from zoneinfo import ZoneInfo; print(ZoneInfo('America/New_York')); print(ZoneInfo('Asia/Shanghai'))"
```

原生 PowerShell 不使用：

```text
scripts/finagent.sh
scripts/run_tests.sh
scripts/lib/finagent_env.sh
```

---

# 7. Secret store 初始化

## 7.1 Ubuntu

```bash
mkdir -p ~/.config/finagent
cp configs/secrets.example.toml ~/.config/finagent/secrets.toml
chmod 600 ~/.config/finagent/secrets.toml
```

编辑：

```bash
nano ~/.config/finagent/secrets.toml
```

检查权限：

```bash
stat -c '%a %n' ~/.config/finagent/secrets.toml
```

期望：

```text
600 ~/.config/finagent/secrets.toml
```

## 7.2 Windows PowerShell

```powershell
New-Item -ItemType Directory -Force "$HOME\.config\finagent" | Out-Null
Copy-Item configs\secrets.example.toml "$HOME\.config\finagent\secrets.toml"
notepad "$HOME\.config\finagent\secrets.toml"
```

本轮测试 Alpaca + DeepSeek 时至少需要填写：

```toml
[api_keys]
deepseek_official = "..."

[market_credentials.alpaca]
api_key = "..."
secret_key = "..."
```

**不再需要**在 PowerShell 中逐项执行：

```powershell
$env:ALPACA_API_KEY = "..."
$env:ALPACA_SECRET_KEY = "..."
```

Canonical pull path 会从 host-side secret store 读取。

---

# 8. T0 — 全量 Regression

## Ubuntu

```bash
./scripts/finagent.sh python -m pytest -q
```

Focused：

```bash
python -m pytest -q \
  tests/test_llm_provider_config_v125.py \
  tests/test_market_data_provider_config_v125.py \
  tests/test_agent_llm_phase3c.py
```

## Windows PowerShell

```powershell
$env:PYTHONNOUSERSITE = "1"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
$env:PYTHONUTF8 = "1"
python -m pytest -q
```

Focused：

```powershell
python -m pytest -q `
  tests\test_llm_provider_config_v125.py `
  tests\test_market_data_provider_config_v125.py `
  tests\test_agent_llm_phase3c.py
```

通过条件：

- 全量测试通过；
- LLM provider config/security 测试通过；
- market-data provider config/security 测试通过；
- materialized directory → `bars.csv` resolution 测试通过。

---

# 9. T1 — Public profile 与 Secret 隔离

## 9.1 LLM profile

Ubuntu / Windows 均可运行单行命令：

```text
python -c "from finagent.agents.providers import load_llm_profile; print(load_llm_profile('configs/llm.toml'))"
```

输出不得包含真实 API key。

## 9.2 Market-data profile

```text
python -c "from finagent.data import load_market_data_profile; print(load_market_data_profile('configs/market_data.toml','alpaca_primary'))"
```

期望包含：

```text
provider='alpaca'
secret_id='alpaca'
```

不得包含：

```text
api_key value
secret_key value
```

## 9.3 Git credential 检查

Ubuntu：

```bash
git status --short
git ls-files | grep -i secret || true
```

Windows PowerShell：

```powershell
git status --short
git ls-files | Select-String -Pattern "secret" -CaseSensitive:$false
```

允许 tracked example：

```text
configs/secrets.example.toml
configs/llm-secrets.example.toml
```

不得提交真实 `secrets.toml`。

---

# 10. T2 — 真实 LLM Provider Connectivity

## 10.1 DeepSeek 官方 — 必测

Ubuntu：

```bash
python scripts/smoke_llm_provider.py \
  configs/llm.toml \
  --profile deepseek_official_v4_pro
```

Windows PowerShell：

```powershell
python scripts/smoke_llm_provider.py `
  configs\llm.toml `
  --profile deepseek_official_v4_pro
```

## 10.2 硅基流动 — 必测接口

Ubuntu：

```bash
python scripts/smoke_llm_provider.py \
  configs/llm.toml \
  --profile siliconflow_deepseek_v4_pro
```

Windows PowerShell：

```powershell
python scripts/smoke_llm_provider.py `
  configs\llm.toml `
  --profile siliconflow_deepseek_v4_pro
```

## 10.3 OpenAI — 可选

Ubuntu：

```bash
python scripts/smoke_llm_provider.py \
  configs/llm.toml \
  --profile openai
```

Windows PowerShell：

```powershell
python scripts/smoke_llm_provider.py `
  configs\llm.toml `
  --profile openai
```

通过条件：输出只包含 public provider/model、usage、response metadata，不包含 Authorization header 或 key。

---

# 11. T3 — 真实市场数据 Provider 与质量门

## 11.1 Alpaca public config 检查

Tracked market config：

```text
configs/markets/us_etf_agent_data_alpaca.toml
```

应包含：

```toml
provider = "alpaca"
market_data_config_path = "configs/market_data.toml"
market_data_profile = "alpaca_primary"
```

无需设置 `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` 环境变量。

## 11.2 Alpaca pull — 必测

Ubuntu：

```bash
python scripts/pull_market_data.py \
  configs/markets/us_etf_agent_data_alpaca.toml
```

Windows PowerShell：

```powershell
python scripts/pull_market_data.py `
  configs\markets\us_etf_agent_data_alpaca.toml
```

也可显式覆盖 host secret 文件路径。

Ubuntu：

```bash
python scripts/pull_market_data.py \
  configs/markets/us_etf_agent_data_alpaca.toml \
  --secrets-file ~/.config/finagent/secrets.toml
```

Windows PowerShell：

```powershell
python scripts/pull_market_data.py `
  configs\markets\us_etf_agent_data_alpaca.toml `
  --secrets-file "$HOME\.config\finagent\secrets.toml"
```

Pull 成功后必须存在：

```text
data/market/us_etf_alpaca/bars.csv
data/market/us_etf_alpaca/manifest.json
data/market/us_etf_alpaca/quality_report.json
```

Ubuntu 检查：

```bash
test -f data/market/us_etf_alpaca/bars.csv
test -f data/market/us_etf_alpaca/manifest.json
```

Windows PowerShell：

```powershell
Test-Path data\market\us_etf_alpaca\bars.csv
Test-Path data\market\us_etf_alpaca\manifest.json
```

均应返回存在/True。

## 11.3 Validate materialized dataset

Validator 现在支持两种调用：

```text
1. 直接传 bars.csv
2. 传 materialized directory，自动解析 <dir>/bars.csv
```

Ubuntu：

```bash
python scripts/validate_market_data.py \
  data/market/us_etf_alpaca
```

Windows PowerShell：

```powershell
python scripts/validate_market_data.py `
  data\market\us_etf_alpaca
```

也可显式：

```powershell
python scripts/validate_market_data.py `
  data\market\us_etf_alpaca\bars.csv
```

### 重要前置条件

如果 pull 阶段失败，不要继续把“不存在的输出目录”当作有效数据执行 validate。

现在 validator 对不存在的路径会明确提示：

```text
run pull_market_data.py successfully before validation
```

而不是把目录误当 CSV 后产生难以定位的 `path.open()` traceback。

## 11.4 AKShare secondary

AKShare profile 不读取 secret 文件。

Ubuntu：

```bash
python scripts/pull_market_data.py \
  configs/markets/us_etf_agent_data_akshare.toml
python scripts/validate_market_data.py \
  data/market/us_etf_akshare
```

Windows PowerShell：

```powershell
python scripts/pull_market_data.py `
  configs\markets\us_etf_agent_data_akshare.toml
python scripts/validate_market_data.py `
  data\market\us_etf_akshare
```

必须记录：

```text
provider
data_version
normalized_sha256
symbol set
calendar range
quality_passed
```

---

# 12. T4 — Deterministic Baseline

目的：先证明 market/backtest numerical pipeline 与 LLM 无关且可重复。

Ubuntu：

```bash
python scripts/run_market_backtest.py \
  configs/markets/us_etf_smoke.toml
```

Windows PowerShell：

```powershell
python scripts/run_market_backtest.py `
  configs\markets\us_etf_smoke.toml
```

通过条件：

- 输入 digest 固定；
- chronology / execution lag 明确；
- 输出指标有限；
- 同一 commit + data + config 重复执行一致；
- 不依赖 LLM credential。

---

# 13. T5 — Canonical Real-LLM Agent Research

DeepSeek 官方为主路径。

Ubuntu：

```bash
python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.toml
```

Windows PowerShell：

```powershell
python scripts/run_agent_market_research.py `
  configs\markets\us_etf_agent_research.toml
```

通过条件：

1. 自动选择 DeepSeek 官方 profile；
2. real LLM request 成功；
3. generated feature 通过 FeatureSpec / AST validation；
4. restricted sandbox 正常；
5. 进入 nested market research；
6. research program denominator / alpha budget 有记录；
7. report / SQLite evidence 无 LLM API key；
8. report / SQLite evidence 无 market-data credential；
9. Agent 不能控制最终 portfolio/risk/execution。

硅基流动端到端测试必须使用独立的：

```text
task_id
program_id
family_id
state_dir
report_path
```

不能覆盖 DeepSeek 官方已经冻结的 candidate family。

---

# 14. T6 — Credential 负向测试

## 14.1 LLM secret 缺失

Ubuntu：

```bash
FINAGENT_SECRETS_FILE=/definitely/missing/finagent-secrets.toml \
python scripts/smoke_llm_provider.py \
  configs/llm.toml \
  --profile deepseek_official_v4_pro
```

Windows PowerShell：

```powershell
$env:FINAGENT_SECRETS_FILE = "$PWD\missing-finagent-secrets.toml"
python scripts/smoke_llm_provider.py `
  configs\llm.toml `
  --profile deepseek_official_v4_pro
Remove-Item Env:FINAGENT_SECRETS_FILE
```

必须在网络请求前 fail closed。

## 14.2 Market-data secret 缺失

Ubuntu：

```bash
python scripts/pull_market_data.py \
  configs/markets/us_etf_agent_data_alpaca.toml \
  --secrets-file /definitely/missing/finagent-secrets.toml
```

Windows PowerShell：

```powershell
python scripts/pull_market_data.py `
  configs\markets\us_etf_agent_data_alpaca.toml `
  --secrets-file "$PWD\missing-finagent-secrets.toml"
```

必须在构造 Alpaca SDK client / 发起 provider request 前失败。

## 14.3 Public market profile 中出现 credential

由：

```text
tests/test_market_data_provider_config_v125.py
```

验证。直接在 tracked/public profile 写 `api_key` / `secret_key` / `token` 必须报错。

## 14.4 POSIX mode gate

```bash
chmod 644 /tmp/finagent-secrets.toml
```

LLM 或收费 market-data provider 加载该文件都必须拒绝，并提示 `chmod 600`。

---

# 15. T7 — Factor Quant / Feedback / Ensemble 1.2.5

Ubuntu：

```bash
python -m pytest -q \
  tests/test_factor_quant_v2_124.py \
  tests/test_factor_ensemble_wiring_v124.py \
  tests/test_ensemble_validation_feedback_v125.py \
  tests/test_agent_factor_discovery_v123.py \
  tests/test_agent_factor_workflow_v123.py
```

Windows PowerShell：

```powershell
python -m pytest -q `
  tests\test_factor_quant_v2_124.py `
  tests\test_factor_ensemble_wiring_v124.py `
  tests\test_ensemble_validation_feedback_v125.py `
  tests\test_agent_factor_discovery_v123.py `
  tests\test_agent_factor_workflow_v123.py
```

必须验证：

- IC / RankIC / IC decay；
- quantile spread / turnover / coverage；
- factor correlation；
- development-only Quant Feedback；
- rejected/failed candidates 保留在完整 denominator；
- Ensemble 为完整 `GeneratedFeatureEnsembleAlphaModel`；
- `K + 1` formal validation；
- Multiplicity / DSR / PBO / Reality Check；
- outer evidence 不反向进入 development feedback。

---

# 16. T8 — Frozen Replay 且禁止读取 LLM Secret

完成一次真实 Agent generation 后：

Ubuntu：

```bash
FINAGENT_SECRETS_FILE=/definitely/missing/finagent-secrets.toml \
python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.toml \
  --frozen-family-report reports/us_etf_agent_market_research.json \
  --report reports/us_etf_agent_market_replay.json \
  --assert-replay
```

Windows PowerShell：

```powershell
$env:FINAGENT_SECRETS_FILE = "$PWD\missing-finagent-secrets.toml"
python scripts/run_agent_market_research.py `
  configs\markets\us_etf_agent_research.toml `
  --frozen-family-report reports\us_etf_agent_market_research.json `
  --report reports\us_etf_agent_market_replay.json `
  --assert-replay
Remove-Item Env:FINAGENT_SECRETS_FILE
```

必须满足：

```text
LLM call count = 0
LLM secret access = 0
exact generated feature digests reused
research budget not double-spent
replay validation passes
```

注意：replay 仍然读取已经物化的 market data 文件，但不应重新调用 Alpaca API。因此它不需要 Alpaca credential。

---

# 17. T9 — Frozen-family Cross-Provider Validation

AKShare 数据必须先成功物化。

## 17.1 在 AKShare 上复算 frozen family

Ubuntu：

```bash
python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.toml \
  --bars data/market/us_etf_akshare/bars.csv \
  --manifest data/market/us_etf_akshare/manifest.json \
  --provider akshare \
  --frozen-family-report reports/us_etf_agent_market_research.json \
  --report reports/us_etf_agent_market_research_akshare.json
```

Windows PowerShell：

```powershell
python scripts/run_agent_market_research.py `
  configs\markets\us_etf_agent_research.toml `
  --bars data\market\us_etf_akshare\bars.csv `
  --manifest data\market\us_etf_akshare\manifest.json `
  --provider akshare `
  --frozen-family-report reports\us_etf_agent_market_research.json `
  --report reports\us_etf_agent_market_research_akshare.json
```

## 17.2 比较 Provider evidence

Ubuntu：

```bash
python scripts/validate_agent_market_research.py \
  reports/us_etf_agent_market_research.json \
  reports/us_etf_agent_market_research_akshare.json \
  --mode cross_provider \
  --left-bars data/market/us_etf_alpaca/bars.csv \
  --right-bars data/market/us_etf_akshare/bars.csv \
  --output reports/us_etf_agent_cross_provider_validation.json \
  --store .finagent/agent-market-us/agent_market_validation.sqlite
```

Windows PowerShell：

```powershell
python scripts/validate_agent_market_research.py `
  reports\us_etf_agent_market_research.json `
  reports\us_etf_agent_market_research_akshare.json `
  --mode cross_provider `
  --left-bars data\market\us_etf_alpaca\bars.csv `
  --right-bars data\market\us_etf_akshare\bars.csv `
  --output reports\us_etf_agent_cross_provider_validation.json `
  --store .finagent\agent-market-us\agent_market_validation.sqlite
```

通过条件：provider/data_version/calendars/financial differences 均显式记录，不进行新的 LLM generation。

---

# 18. T10 — Static / Build / Dependency Gate

Ubuntu：

```bash
ruff check src tests scripts --select E9,F63,F7,F82
ruff check \
  src/finagent/agents/providers \
  src/finagent/data/ingestion \
  tests/test_llm_provider_config_v125.py \
  tests/test_market_data_provider_config_v125.py \
  scripts/pull_market_data.py \
  scripts/validate_market_data.py \
  --select E4,E7,E9,F
python -m build
python -m pip check
```

Windows PowerShell：

```powershell
ruff check src tests scripts --select E9,F63,F7,F82
ruff check `
  src\finagent\agents\providers `
  src\finagent\data\ingestion `
  tests\test_llm_provider_config_v125.py `
  tests\test_market_data_provider_config_v125.py `
  scripts\pull_market_data.py `
  scripts\validate_market_data.py `
  --select E4,E7,E9,F
python -m build
python -m pip check
```

---

# 19. 对本次两个报错的解释

## 19.1 `ALPACA_API_KEY and ALPACA_SECRET_KEY are required`

旧 canonical CLI 直接调用：

```python
AlpacaMarketDataIngestor.from_environment()
```

因此即使已经采用 LLM secret config，market-data path 仍要求单独设置环境变量，接口不一致。

v1.2 修正为：

```text
us_etf_agent_data_alpaca.toml
        ↓
market_data_profile = alpaca_primary
        ↓
configs/market_data.toml
        ↓
secret_id = alpaca
        ↓
~/.config/finagent/secrets.toml
        ↓
StockHistoricalDataClient
```

测试人员只需要维护同一个 host-side secret store。

## 19.2 `FileNotFoundError: data\\market\\us_etf_alpaca`

这里有两个原因：

1. 前一步 Alpaca pull 已失败，因此 output 尚未成功物化；
2. 旧 `validate_market_data.py` 只接受 CSV 文件，但旧文档传入的是目录，两者 CLI contract 不一致。

v1.2 后 validator 同时接受：

```text
data/market/us_etf_alpaca
```

和：

```text
data/market/us_etf_alpaca/bars.csv
```

目录模式自动解析 `bars.csv`。如果路径不存在，会明确提示先完成 `pull_market_data.py`。

---

# 20. GO / NO-GO 标准

## GO 必须满足

- [ ] Ubuntu/Python 3.11 环境通过；
- [ ] Windows/Python 3.11 环境通过；
- [ ] 全量 regression 通过；
- [ ] LLM provider config/security tests 通过；
- [ ] market-data provider config/security tests 通过；
- [ ] DeepSeek 官方 V4-Pro real smoke 通过；
- [ ] 硅基流动 V4-Pro real smoke 通过；
- [ ] Alpaca 可仅依赖 host-side secret store 成功 pull；
- [ ] 不依赖 `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` shell 配置；
- [ ] Alpaca materialized directory validation 通过；
- [ ] AKShare credential-free path 通过；
- [ ] market-data credential 不进入 manifest/report/Agent/LLM 上下文；
- [ ] 至少一次 DeepSeek official real Agent generation 成功；
- [ ] Factor Quant / Feedback / denominator / Ensemble K+1 通过；
- [ ] DSR / PBO / Reality Check 等正式指标有限；
- [ ] replay 在缺失 LLM secret 时通过；
- [ ] replay 不重新调用数据 Provider；
- [ ] frozen-family cross-provider validation 完成；
- [ ] build / pip check / Ruff gate 通过。

## 任一以下情况为 NO-GO

- API key 出现在 prompt / metadata / result / manifest / SQLite audit 或异常日志中；
- public market-data profile 允许直接写真实 credential；
- canonical Alpaca pull 仍强制依赖 `from_environment()`；
- market profile provider 与 study provider 可以静默不一致；
- validator 将 materialized directory 错当普通 CSV；
- DeepSeek official structured generation 不稳定；
- replay 产生第二次 LLM 调用或重新拉取 Provider 数据；
- candidate denominator 漂移；
- outer evidence 进入 development feedback；
- provider/data_version 被静默替换；
- build/dependency gate 失败。

---

# 21. 测试记录模板

```text
FinAgent 1.2.5 System Acceptance
=================================
Date:
Commit SHA:
OS:
Shell: bash / PowerShell
Python:
Conda env:

Environment
-----------
Conda create/update: PASS / FAIL
Editable install: PASS / FAIL
pip check: PASS / FAIL
Windows tzdata: PASS / FAIL / N/A

Secret store
------------
Path recorded without contents: YES / NO
Secret outside repo: PASS / FAIL
POSIX 0600 gate: PASS / FAIL / N/A

LLM providers
-------------
DeepSeek official smoke: PASS / FAIL
SiliconFlow smoke: PASS / FAIL
OpenAI optional smoke: PASS / FAIL / NOT RUN
LLM credential leak scan: PASS / FAIL

Market data providers
---------------------
Alpaca profile: alpaca_primary
Alpaca shell env credentials required: NO / YES
Alpaca pull: PASS / FAIL
Alpaca data_version:
Alpaca bars SHA256:
Alpaca quality gate: PASS / FAIL
Directory validator: PASS / FAIL
AKShare pull: PASS / FAIL
Market credential leak scan: PASS / FAIL

Agent generation
----------------
LLM profile:
Model:
Requested candidates:
Valid candidates:
AST failures:
Sandbox failures:
Research report:

1.2.5 quantitative surface
--------------------------
Factor Quant v2: PASS / FAIL
Quant Feedback v2: PASS / FAIL
Complete denominator: PASS / FAIL
Ensemble K+1: PASS / FAIL
Multiplicity: PASS / FAIL
DSR: PASS / FAIL
PBO: PASS / FAIL
Reality Check: PASS / FAIL

Replay
------
Frozen family report:
LLM secret deliberately unavailable: YES / NO
LLM call count: 0 / NONZERO
Market provider network call during replay: 0 / NONZERO
Exact replay: PASS / FAIL

Final
-----
GO / NO-GO
Blocking defects:
Non-blocking observations:
```

---

# 22. 推荐执行顺序

```text
T0  full regression
 ↓
T1  LLM + market-data public config / secret isolation
 ↓
T2  DeepSeek + SiliconFlow real smoke
 ↓
T3  Alpaca secure-config pull + validation
 ↓
     AKShare secondary pull + validation
 ↓
T4  deterministic baseline
 ↓
T5  DeepSeek real Agent generation
 ↓
T6  credential negative tests
 ↓
T7  Factor Quant / Feedback / Ensemble K+1
 ↓
T8  replay with deliberately unavailable LLM secret
 ↓
T9  frozen-family cross-provider validation
 ↓
T10 static / build / dependency gate
 ↓
GO / NO-GO
```

执行原则：先验证**环境、shell 语法、credential 边界和 Provider connectivity**，再消费真实 LLM/API 调用；随后验证量化研究链，最后通过无 LLM secret replay 与 cross-provider validation 检查可重复性和治理边界。
