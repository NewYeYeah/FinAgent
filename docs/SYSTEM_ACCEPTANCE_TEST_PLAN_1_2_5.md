# FinAgent 1.2.5 系统验收测试计划

**文档版本：** v1.1  
**修订日期：** 2026-08-26  
**适用代码基线：** FinAgent 1.2.5 acceptance surface  
**基线分支：** `main`  
**测试时必须记录：** `git rev-parse HEAD` 的实际提交，不再绑定旧固定 SHA  
**适用系统：** Ubuntu 22.04/24.04、Windows 10/11 x64（原生 PowerShell）  
**LLM 主路径：** DeepSeek 官方 DeepSeek-V4-Pro  
**LLM 兼容路径：** 硅基流动 DeepSeek-V4-Pro、OpenAI Responses API  
**重要约束：** 本轮验收不消费正式 sealed holdout，不执行 live broker，不以“策略是否盈利”作为通过标准。

> 接口口径以 2026-08-26 的官方文档为准。DeepSeek V4-Pro 通过 OpenAI-compatible Chat Completions 接入；硅基流动通过 OpenAI-compatible Chat Completions 接入；OpenAI 原 Responses adapter 保留为可选配置。模型供应商可能更新模型 ID 或参数支持，正式验收前必须再次核对供应商文档。

---

# 1. 测试目标

本轮系统验收回答以下问题：

1. FinAgent 能否在 Ubuntu 与原生 Windows 上建立可重复的 Python 测试环境；
2. Alpaca / AKShare 等真实数据能否稳定落入同一 FinAgent 数据契约；
3. deterministic market baseline 是否可重复运行；
4. DeepSeek 官方 V4-Pro 能否作为 canonical LLM 生成通过 AST / sandbox 约束的真实因子代码；
5. 硅基流动提供的 DeepSeek V4-Pro OpenAI-compatible 接口是否可作为第二 LLM 路径；
6. OpenAI provider 是否仍保持可选兼容；
7. API key 是否与 Agent/LLM 请求、prompt、metadata、审计记录和结果文件隔离；
8. Factor Quant Engine v2 是否正确计算 IC、RankIC、IC decay、quantile spread、turnover、coverage 与 factor correlation；
9. Agent 是否真正利用 development-only Quant Feedback v2 进行下一轮候选改进；
10. 多轮 discovery 是否完整保留 candidate denominator；
11. 多因子 Ensemble 是否以完整 AlphaModel 方式独立拟合与验证；
12. Formal validation 是否在同一 outer fold 中对 `K 个单因子 + 1 个 Ensemble` 执行 Multiplicity / DSR / PBO / Reality Check；
13. frozen-family deterministic replay 是否在**完全没有 LLM credential**的情况下仍能通过；
14. 同一 frozen family 在 Alpaca 与 AKShare 间是否可执行 cross-provider robustness 检查；
15. 当前系统是否达到进入 1.2.6 的 GO 条件。

核心判据：

```text
系统行为可解释
+ 数据身份可追踪
+ LLM provider 可替换
+ credential 不进入模型上下文
+ 数值输出有限
+ candidate denominator 不漂移
+ replay 可重复且不依赖 LLM
+ provider 差异不被静默吞掉
```

以下内容不是验收标准：

```text
Sharpe > 1
Ensemble 必须击败最佳单因子
LLM 每次必须生成完全相同的候选
```

---

# 2. 1.2.5 LLM 架构与接口基线

## 2.1 Provider 矩阵

| Profile | Provider | Base URL | Model | API surface | 角色 |
|---|---|---|---|---|---|
| `deepseek_official_v4_pro` | DeepSeek 官方 | `https://api.deepseek.com` | `deepseek-v4-pro` | Chat Completions | **主力 / 必测** |
| `siliconflow_deepseek_v4_pro` | 硅基流动 | `https://api.siliconflow.cn/v1` | `deepseek-ai/DeepSeek-V4-Pro` | Chat Completions | 第三方备选 / 必测接口 |
| `openai` | OpenAI | SDK 默认或显式 `base_url` | 测试账户可用模型 | Responses API | 可选兼容 |

公共路由配置位于：

```text
configs/llm.toml
```

Canonical research config 通过：

```toml
llm_config_path = "configs/llm.toml"
llm_profile = "deepseek_official_v4_pro"
```

选择主模型。

CLI 可临时覆盖 profile：

```bash
python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.toml \
  --llm-profile siliconflow_deepseek_v4_pro
```

注意：不同 LLM 做独立首次生成测试时，应使用不同的 `task_id`、`program_id`、`family_id`、`state_dir` 和 `report_path`，不得让第二个 LLM 在已冻结的第一组 research identity 上静默替换候选。

## 2.2 DeepSeek V4-Pro 接入原则

当前 DeepSeek V4-Pro 主路径使用 Chat Completions，而不是直接复用 OpenAI Responses adapter。

DeepSeek adapter 默认启用：

```text
thinking = true
reasoning_effort = high
response_format = json_object
```

FinAgent 同时在 system message 中明确要求只返回符合指定 JSON Schema 的 JSON object，再由现有 feature/planner validation 做第二层结构校验。

## 2.3 硅基流动接入原则

硅基流动使用 OpenAI-compatible Chat Completions 与 JSON mode。

由于当前硅基流动模型目录已提供 DeepSeek-V4-Pro，但推理参数文档对 V4-Pro 的支持口径并不完全一致，因此 FinAgent **默认不向该模型强制传入 `reasoning_effort` 或 `thinking` 私有参数**。这不是功能缺失，而是为了避免在测试阶段依赖未明确承诺的 provider-specific 参数。

## 2.4 OpenAI 兼容原则

原 `OpenAIResponsesProvider` 保留，不改为 DeepSeek-compatible adapter。其用途是：

- 保持既有 OpenAI Responses API 测试能力；
- 允许用户在 `configs/llm.toml` 中选择 `openai` profile；
- 不影响 DeepSeek 成为 canonical 主模型。

---

# 3. Credential 安全边界

## 3.1 设计

FinAgent 将“公共 LLM 配置”和“真实 secret”拆为两个文件：

```text
configs/llm.toml
  provider / model / base_url / secret_id
                 |
                 v
        host-side config loader
                 ^
                 |
~/.config/finagent/secrets.toml
  actual API keys
                 |
                 v
           SDK client constructor
                 |
                 v
        LLMProvider.complete()
                 |
                 v
        LLMRequest / Agent prompt
        （不存在 API key）
```

仓库只提供：

```text
configs/llm-secrets.example.toml
```

该文件只能包含 placeholder。

真实 secret 文件默认位于仓库外：

```text
~/.config/finagent/secrets.toml
```

也可用环境变量只覆盖**文件路径**：

```text
FINAGENT_SECRETS_FILE
```

不得用它存放 key 本身。

## 3.2 必须满足的安全约束

1. `LLMProfile` 不包含 API key；
2. API key 只在 host-side loader 中短暂读取，并直接用于 SDK client 构造；
3. API key 不进入 `LLMRequest`；
4. API key 不进入 `AgentTask.metadata`；
5. API key 不进入 prompt / system message；
6. API key 不进入 research report；
7. API key 不进入 durable Agent/LLM audit payload；
8. provider 异常不得原样持久化上游 HTTP/SDK exception text；
9. POSIX 下真实 secret 文件默认要求权限不宽于 `0600`；
10. `.gitignore` 必须忽略 `configs/*secrets*.toml`，但允许 example template 被跟踪；
11. frozen-family replay 不得读取 secret 文件，也不得实例化真实 LLM provider。

## 3.3 安全边界的真实含义

这里的目标是：

> **模型本身无法通过正常 prompt/request/tool payload 获得 API key。**

这不是对任意恶意本地代码的绝对隔离。如果未来给 Agent 增加任意 shell、任意文件读取、Python object introspection 等高权限工具，则同进程 SDK client 内部仍可能持有认证信息。此类工具必须采用独立 sandbox/process，并显式禁止访问 secret 路径和宿主进程对象。

因此本轮验收禁止把任意文件系统读取或 shell 权限暴露给 LLM。

---

# 4. 环境与安装

## 4.1 环境矩阵

| 环境 | 状态 | 用途 |
|---|---|---|
| Ubuntu 24.04 + Python 3.11 | 主参考环境 | 完整测试 |
| Ubuntu + Python 3.12/3.13 | CI 对齐 | regression |
| Windows 11 + Python 3.11 | Windows 主测试环境 | 完整测试 |
| Windows + Python 3.12/3.13 | 可选 | compatibility |
| WSL2 Ubuntu | 可选 | 不能替代原生 Windows 验收 |

GitHub Actions 当前仍以 Ubuntu 为主，因此 Windows 原生测试必须保留人工验收记录。

## 4.2 Conda 安装方式

1.2.5 测试基线已经取消 `environment/environment.yml` 内部位置敏感的 `pip -e .`。

因此环境创建和项目安装必须拆成两步。

Ubuntu：

```bash
git clone https://github.com/NewYeYeah/FinAgent.git
cd FinAgent
conda env create -f environment/environment.yml
conda activate finagent
python -m pip install -e ".[dev,llm,cn-free,us-market,a-share]"
```

若环境已存在：

```bash
conda env update -n finagent -f environment/environment.yml --prune
conda activate finagent
python -m pip install -e ".[dev,llm,cn-free,us-market,a-share]"
```

Windows PowerShell：

```powershell
git clone https://github.com/NewYeYeah/FinAgent.git
Set-Location FinAgent
conda env create -f environment/environment.yml
conda activate finagent
python -m pip install -e ".[dev,llm,cn-free,us-market,a-share]"
python -m pip install tzdata
```

验证时区：

```powershell
python -c "from zoneinfo import ZoneInfo; print(ZoneInfo('America/New_York')); print(ZoneInfo('Asia/Shanghai'))"
```

原生 Windows 不使用：

```text
scripts/finagent.sh
scripts/run_tests.sh
scripts/lib/finagent_env.sh
```

## 4.3 基础环境记录

每次正式验收必须保存：

```text
Git commit SHA
OS / kernel
Python version
Conda environment
pip check
LLM public profile
LLM public model id
market-data provider
data_version
bars SHA256
research config fingerprint / path
```

不得保存：

```text
API key
secret 文件正文
Authorization header
完整 SDK debug HTTP request
```

---

# 5. LLM secret 配置

## 5.1 Linux / Ubuntu

```bash
mkdir -p ~/.config/finagent
cp configs/llm-secrets.example.toml ~/.config/finagent/secrets.toml
chmod 600 ~/.config/finagent/secrets.toml
```

然后编辑外部文件：

```toml
[api_keys]
deepseek_official = "<your key>"
siliconflow = "<your key>"
openai = "<optional key>"
```

只填写实际要测试的 provider。

检查权限：

```bash
stat -c '%a %n' ~/.config/finagent/secrets.toml
```

期望：

```text
600 ~/.config/finagent/secrets.toml
```

## 5.2 Windows PowerShell

```powershell
New-Item -ItemType Directory -Force "$HOME\.config\finagent" | Out-Null
Copy-Item configs\llm-secrets.example.toml "$HOME\.config\finagent\secrets.toml"
notepad "$HOME\.config\finagent\secrets.toml"
```

Windows 当前不使用 POSIX mode-bit 校验，但仍要求：

- 文件位于用户私有目录；
- 不放入 Git 仓库；
- 不上传到测试报告；
- 不复制到 Agent 可读 workspace。

---

# 6. T0 — 全量 Regression

Ubuntu：

```bash
./scripts/finagent.sh python -m pytest -q
```

Windows：

```powershell
$env:PYTHONNOUSERSITE = "1"
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
$env:PYTHONUTF8 = "1"
python -m pytest -q
```

额外执行 LLM 相关回归：

```bash
python -m pytest -q \
  tests/test_llm_provider_config_v125.py \
  tests/test_agent_llm_phase3c.py
```

通过条件：

- 全量测试通过；
- DeepSeek adapter JSON mode 测试通过；
- SiliconFlow adapter JSON mode 测试通过；
- provider exception secret-redaction 测试通过；
- public profile 不含 secret 测试通过；
- POSIX `0600` negative test 通过。

---

# 7. T1 — 公共配置与 Secret 隔离

首先只读取 public profile，不触碰 secret：

```bash
python -c "from finagent.agents.providers import load_llm_profile; print(load_llm_profile('configs/llm.toml'))"
```

期望：

```text
provider='deepseek'
model='deepseek-v4-pro'
secret_id='deepseek_official'
```

输出中不得包含真实 API key。

检查 Git：

```bash
git status --short
git ls-files | grep -i secret || true
```

允许 tracked：

```text
configs/llm-secrets.example.toml
```

不得存在已提交的真实 secret 文件。

通过条件：

- public config 可完整决定 provider/model/base_url；
- secret alias 可见，但 secret value 不可见；
- git working tree 不包含真实 credential；
- 正式日志、report、SQLite evidence 中不出现已知 API key 字符串。

---

# 8. T2 — 真实 LLM Provider Connectivity Smoke

使用最小结构化输出脚本：

```text
scripts/smoke_llm_provider.py
```

## 8.1 DeepSeek 官方 — 必测

```bash
python scripts/smoke_llm_provider.py \
  configs/llm.toml \
  --profile deepseek_official_v4_pro
```

要求：

- HTTP/API 调用成功；
- `provider == deepseek`；
- 返回 JSON object；
- `output.ok == true`；
- model 与当前官方 V4-Pro 路径一致；
- 输出只记录 public profile/model、usage、latency、response id；
- 不打印 API key 或 Authorization header。

## 8.2 硅基流动 DeepSeek V4-Pro — 必测接口

```bash
python scripts/smoke_llm_provider.py \
  configs/llm.toml \
  --profile siliconflow_deepseek_v4_pro
```

要求同上，并确认：

```text
provider == siliconflow
```

本项不要求与 DeepSeek 官方输出 token 数或 latency 一致。

## 8.3 OpenAI — 可选

首先在 `configs/llm.toml` 的 `openai` profile 中填写当前账户可用的公开 model ID，不填写 key。

然后：

```bash
python scripts/smoke_llm_provider.py \
  configs/llm.toml \
  --profile openai
```

OpenAI 不作为 1.2.5 DeepSeek-first GO 的强制真实调用条件，但原 adapter 的 unit regression 必须通过。

---

# 9. T3 — 真实市场数据与质量门

本轮 US reference universe：

```text
SPY / QQQ / IWM / DIA
```

## 9.1 Alpaca primary

Ubuntu：

```bash
./scripts/finagent.sh python scripts/pull_market_data.py \
  configs/markets/us_etf_agent_data_alpaca.toml
./scripts/finagent.sh python scripts/validate_market_data.py \
  data/market/us_etf_alpaca
```

Windows：

```powershell
python scripts/pull_market_data.py configs/markets/us_etf_agent_data_alpaca.toml
python scripts/validate_market_data.py data/market/us_etf_alpaca
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

## 9.2 AKShare secondary

```bash
python scripts/pull_market_data.py \
  configs/markets/us_etf_agent_data_akshare.toml
python scripts/validate_market_data.py \
  data/market/us_etf_akshare
```

AKShare 用于 development/cross-provider robustness，不作为与 Alpaca 数值完全一致的来源。

---

# 10. T4 — Deterministic Baseline

使用现有 deterministic market backtest CLI，在相同 immutable market dataset 上完成 baseline。

通过条件：

- 输入数据 digest 固定；
- chronology / execution lag 明确；
- 输出指标均为有限值；
- 同一 commit、同一数据和同一 config 重复执行结果一致；
- baseline 不依赖 LLM credential。

本项的作用是区分：

```text
LLM generation failure
```

和：

```text
market/backtest numerical pipeline failure
```

---

# 11. T5 — Canonical Real-LLM Agent Research

## 11.1 DeepSeek 官方主路径 — 必测

Canonical config 已默认：

```toml
llm_profile = "deepseek_official_v4_pro"
```

首次真实生成建议为 fresh identity 使用独立的：

```text
task_id
program_id
family_id
state_dir
report_path
```

执行：

```bash
python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.toml
```

通过条件：

1. 配置自动选择 DeepSeek 官方 profile；
2. real LLM request 成功；
3. 生成候选数量符合 `candidate_count`；
4. generated feature 通过 FeatureSpec/AST validation；
5. restricted sandbox 正常；
6. 进入 nested market research；
7. research program denominator 与 alpha budget 有记录；
8. report 中没有 API key；
9. SQLite evidence 中没有 API key；
10. LLM 只能提出候选，不获得最终 portfolio/risk/execution 权限。

## 11.2 硅基流动端到端生成 — 接口验收建议执行

不要直接复用 DeepSeek 官方首次生成的 research identity。复制 market research config 到本地 ignored/untracked config，至少修改：

```text
llm_profile = "siliconflow_deepseek_v4_pro"
task_id
program_id
family_id
state_dir
report_path
```

然后运行相同 CLI。

本测试判断“接口 + generated-feature workflow 是否打通”，不要求两个 LLM 生成同样的因子。

---

# 12. T6 — Credential 负向安全测试

## 12.1 Secret 缺失必须 fail closed

创建一个指向不存在文件的 secret 路径，然后执行真实 LLM smoke：

Ubuntu：

```bash
FINAGENT_SECRETS_FILE=/definitely/missing/finagent-secrets.toml \
python scripts/smoke_llm_provider.py configs/llm.toml \
  --profile deepseek_official_v4_pro
```

必须在 LLM 请求发出前失败。

Windows：

```powershell
$env:FINAGENT_SECRETS_FILE = "$PWD\missing-finagent-secrets.toml"
python scripts/smoke_llm_provider.py configs/llm.toml --profile deepseek_official_v4_pro
Remove-Item Env:FINAGENT_SECRETS_FILE
```

## 12.2 POSIX 权限过宽必须拒绝

在临时 secret 文件上设置：

```bash
chmod 644 /tmp/finagent-secrets.toml
```

加载 provider 必须报错，并提示使用 `chmod 600`。

## 12.3 上游异常不得回显 secret

由：

```bash
python -m pytest -q tests/test_llm_provider_config_v125.py
```

中的 fake upstream exception test 验证。

通过条件：异常中只保留 provider + exception class 等最小诊断信息，不原样记录上游 HTTP/SDK exception body。

---

# 13. T7 — Factor Quant / Feedback / Ensemble 1.2.5 API 验收

运行：

```bash
python -m pytest -q \
  tests/test_factor_quant_v2_124.py \
  tests/test_factor_ensemble_wiring_v124.py \
  tests/test_ensemble_validation_feedback_v125.py \
  tests/test_agent_factor_discovery_v123.py \
  tests/test_agent_factor_workflow_v123.py
```

必须验证：

### Factor Quant v2

- IC；
- RankIC；
- IC decay；
- quantile spread；
- turnover；
- coverage；
- factor correlation；
- development-only feedback 不泄漏 outer validation evidence。

### Cumulative discovery

- 每轮候选均进入完整 search denominator；
- rejected/failed candidate 不被删除；
- feedback 只能修改后续 proposal，不得重写历史 trial。

### Ensemble

- Ensemble 由完整 `GeneratedFeatureEnsembleAlphaModel` 表示；
- 不能用简单拼接单因子收益伪装成 Ensemble；
- 成员选择与权重拟合只使用允许的训练/development evidence。

### Formal K+1 validation

同一 outer fold 中：

```text
K single-factor candidates
+
1 ensemble candidate
```

必须进入同一统计治理面，并得到：

```text
Multiplicity
Deflated Sharpe Ratio
PBO
Reality Check
```

正式 validation metrics 必须是有限值；边界/失败必须显式记录。

---

# 14. T8 — Deterministic Replay 且禁止读取 Secret

本项是本轮新增的关键安全验收。

完成一次 DeepSeek 官方真实 Agent generation 后，执行：

Ubuntu：

```bash
FINAGENT_SECRETS_FILE=/definitely/missing/finagent-secrets.toml \
python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.toml \
  --frozen-family-report reports/us_etf_agent_market_research.json \
  --report reports/us_etf_agent_market_replay.json \
  --assert-replay
```

Windows：

```powershell
$env:FINAGENT_SECRETS_FILE = "$PWD\missing-finagent-secrets.toml"
python scripts/run_agent_market_research.py `
  configs/markets/us_etf_agent_research.toml `
  --frozen-family-report reports/us_etf_agent_market_research.json `
  --report reports/us_etf_agent_market_replay.json `
  --assert-replay
Remove-Item Env:FINAGENT_SECRETS_FILE
```

必须通过。

其含义是：

```text
frozen replay
!= second LLM generation
!= credential access
```

通过条件：

- 不读取 secret 文件；
- 不初始化真实 provider；
- 不发送网络 LLM request；
- exact generated feature digest 被复用；
- replay validation 通过；
- research/search budget 不被重复消费。

---

# 15. T9 — Frozen-family Cross-Provider Validation

使用已冻结候选 family，在 AKShare 数据上复算：

```bash
python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.toml \
  --bars data/market/us_etf_akshare/bars.csv \
  --manifest data/market/us_etf_akshare/manifest.json \
  --provider akshare \
  --frozen-family-report reports/us_etf_agent_market_research.json \
  --report reports/us_etf_agent_market_research_akshare.json
```

然后：

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

通过条件：

- frozen candidate identity 一致；
- provider/data_version 差异显式记录；
- calendar evidence 可核对；
- 金融指标差异被报告，而非被静默“对齐”；
- 不进行新的 LLM generation。

---

# 16. T10 — Static / Build / Dependency Gate

执行：

```bash
ruff check src tests scripts --select E9,F63,F7,F82
python -m build
python -m pip check
```

针对新增 LLM surface 建议额外执行：

```bash
ruff check \
  src/finagent/agents/providers \
  tests/test_llm_provider_config_v125.py \
  scripts/smoke_llm_provider.py \
  scripts/run_agent_market_research.py \
  --select E4,E7,E9,F
```

通过条件：

- build 成功；
- dependency consistency 通过；
- 无 critical Ruff error；
- optional `llm` extra 安装后可使用 OpenAI SDK 作为 DeepSeek/SiliconFlow transport；
- 旧 `llm-openai` extra 仍保留兼容。

---

# 17. GO / NO-GO 标准

## 17.1 GO 必须同时满足

- [ ] Ubuntu/Python 3.11 主环境创建成功；
- [ ] Windows/Python 3.11 主环境创建成功；
- [ ] `environment.yml` 不再触发错误目录下的 editable install；
- [ ] 全量 regression 通过；
- [ ] `tests/test_llm_provider_config_v125.py` 通过；
- [ ] DeepSeek 官方 V4-Pro real smoke 通过；
- [ ] 硅基流动 DeepSeek V4-Pro real smoke 通过；
- [ ] 至少一次 DeepSeek 官方 real Agent feature generation 成功；
- [ ] generated feature AST/sandbox 通过；
- [ ] credential 未出现在 prompt / metadata / report / audit output；
- [ ] POSIX secret permission gate 通过；
- [ ] missing-secret fail-closed 通过；
- [ ] Factor Quant v2 integration 通过；
- [ ] Quant Feedback v2 cumulative behavior 通过；
- [ ] complete candidate denominator 保持不变；
- [ ] K+1 Ensemble formal validation 通过；
- [ ] DSR / PBO / Reality Check 等正式指标均为有限值；
- [ ] deterministic replay 在不存在 secret 文件时仍通过；
- [ ] replay 不重复调用 LLM、不重复消费 research budget；
- [ ] Alpaca primary data quality 通过；
- [ ] frozen-family cross-provider validation 完成并显式报告差异；
- [ ] build / pip check / critical Ruff gate 通过。

OpenAI real API smoke **不是** DeepSeek-first 1.2.5 的强制 GO 条件，但 OpenAI adapter 的软件 regression 必须通过。

## 17.2 任一以下情况为 NO-GO

- API key 出现在 LLM request、prompt、metadata、result JSON、SQLite audit 或异常文本中；
- Agent 可直接读取真实 secret 文件；
- DeepSeek 官方主路径无法稳定完成 structured-output generation；
- SiliconFlow adapter 只能靠未明确支持的私有参数才能运行；
- replay 仍要求 secret 或产生第二次 LLM 调用；
- candidate denominator 在多轮 discovery 中丢失失败/拒绝 trial；
- Ensemble 以外部测试结果选择成员或拟合权重；
- outer evidence 反向进入 development feedback；
- provider/data_version 被静默替换；
- 同一数据/config replay 不确定；
- build 或 dependency consistency 失败。

---

# 18. 测试记录模板

```text
FinAgent 1.2.5 System Acceptance
=================================
Date:
Commit SHA:
OS:
Python:
Conda env:

Environment
-----------
Conda create/update: PASS / FAIL
Editable install: PASS / FAIL
pip check: PASS / FAIL
Windows tzdata: PASS / FAIL / N/A

LLM security/config
-------------------
Public config load: PASS / FAIL
Secret outside repo: PASS / FAIL
POSIX 0600 gate: PASS / FAIL / N/A
Missing-secret fail-closed: PASS / FAIL
Secret leak scan: PASS / FAIL

LLM providers
-------------
DeepSeek official profile: deepseek_official_v4_pro
DeepSeek public model id:
DeepSeek smoke: PASS / FAIL
SiliconFlow profile: siliconflow_deepseek_v4_pro
SiliconFlow public model id:
SiliconFlow smoke: PASS / FAIL
OpenAI optional smoke: PASS / FAIL / NOT RUN

Market data
-----------
Primary provider:
data_version:
bars SHA256:
quality gate: PASS / FAIL
Secondary provider:
cross-provider validation: PASS / FAIL

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
Secret deliberately unavailable: YES / NO
LLM call count during replay: 0 / NONZERO
Exact replay: PASS / FAIL

Final
-----
GO / NO-GO
Blocking defects:
Non-blocking observations:
```

---

# 19. 已知基线事项

1. `pyproject.toml` 的 package version 目前仍可能落后于 1.2.5 acceptance surface；测试报告必须记录实际 commit，不得只凭 `pip show finagent` 的版本号判定代码基线。若进入正式 1.2.5 release/tag，应在发布前统一 package metadata。
2. GitHub Actions 目前以 Ubuntu 为主要 CI 平台，原生 Windows 仍需要本轮人工验收。
3. `scripts/run_agent_market_research.py` 负责 canonical real-LLM + generated feature + governed market path；Factor Quant v2 / cumulative feedback / Ensemble K+1 的完整 1.2.5 surface 目前仍主要通过 API/integration tests 验收，而不是一个单命令 production CLI。
4. LLM credential 隔离保证 key 不进入正常模型上下文，但未来若引入任意 shell/file-system Agent tool，必须重新做 capability sandbox 与 secret namespace 隔离评审。

---

# 20. 推荐执行顺序

```text
T0  full regression
 ↓
T1  public config + secret isolation
 ↓
T2  DeepSeek official real smoke
 ↓
     SiliconFlow real smoke
 ↓
T3  Alpaca / AKShare data quality
 ↓
T4  deterministic baseline
 ↓
T5  DeepSeek official real Agent generation
 ↓
T6  credential negative tests
 ↓
T7  Factor Quant / Feedback / Ensemble K+1
 ↓
T8  replay with deliberately missing secret
 ↓
T9  frozen-family cross-provider validation
 ↓
T10 static / build / dependency gate
 ↓
GO / NO-GO
```

本顺序的原则是先验证**环境、credential 边界和 provider connectivity**，再消费真实 LLM 调用；随后验证 Agent 与量化研究链，最后用“无 secret replay”和 cross-provider validation 检查可重复性与治理边界。
