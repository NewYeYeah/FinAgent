# FinAgent 1.2.5 Provider 凭据配置与 DQ-10 排障附录

**适用范围：** `docs/SYSTEM_ACCEPTANCE_TEST_PLAN_1_2_5.md` 的 Provider 实测阶段  
**适用代码：** FinAgent 1.2.5 acceptance surface  
**系统：** Ubuntu 22.04/24.04、Windows 10/11 PowerShell  
**原则：** public profile 只保存 provider routing / `secret_id`；真实 credential 只写入仓库外 `secrets.toml`。

---

## 1. Canonical secret store

模板：

```text
configs/secrets.example.toml
```

推荐复制到：

```text
Ubuntu : ~/.config/finagent/secrets.toml
Windows: %USERPROFILE%\.config\finagent\secrets.toml
```

结构：

```toml
[api_keys]
deepseek_official = "..."
siliconflow = "..."
openai = "..."

[market_credentials.alpaca]
api_key = "..."
secret_key = "..."

[market_credentials.tushare]
token = "..."

[market_credentials.hithink]
api_key = "..."
```

只填写实际需要测试的 Provider。不要将真实 credential 写入：

```text
configs/market_data.toml
configs/markets/*.toml
AgentTask.metadata
research report
Git repository
```

Ubuntu 需将 secret file 收紧为：

```bash
chmod 600 ~/.config/finagent/secrets.toml
```

Windows 当前不检查 POSIX mode bits，但 secret 文件仍应位于当前用户私有目录。

---

# 2. Alpaca

## 2.1 接口状态

FinAgent 当前实现：

```text
AlpacaMarketDataIngestor
market = us_equity
asset_type = equity / etf
historical daily = supported
historical minute = capability declared
```

当前验收使用 US ETF daily bars。

Alpaca 官方 Market Data API 支持 IEX 与 SIP feed：

- `iex`：单一 IEX 交易所，适合初始应用测试；
- `sip`：全美交易所 consolidated feed，更适合研究和价格完整性要求较高的场景。

官方文档：

```text
https://docs.alpaca.markets/us/docs/market-data-faq
https://docs.alpaca.markets/us/v1.1/docs/historical-stock-data-1
```

## 2.2 获取密钥

1. 登录 Alpaca Dashboard；
2. 在 API Keys 区域创建/查看 API Key；
3. 保存 Key ID 与 Secret Key。

不要提交到仓库。

## 2.3 FinAgent 配置

Public profile：

```toml
# configs/market_data.toml
[market_data.profiles.alpaca_primary]
provider = "alpaca"
secret_id = "alpaca"
```

Secret store：

```toml
[market_credentials.alpaca]
api_key = "<Alpaca API Key ID>"
secret_key = "<Alpaca Secret Key>"
```

Canonical config：

```text
configs/markets/us_etf_agent_data_alpaca.toml
```

拉取：

### Ubuntu

```bash
python scripts/pull_market_data.py \
  configs/markets/us_etf_agent_data_alpaca.toml \
  --show-capabilities
```

### Windows PowerShell

```powershell
python scripts/pull_market_data.py `
  configs\markets\us_etf_agent_data_alpaca.toml `
  --show-capabilities
```

## 2.4 IEX 与 SIP 的测试口径

当前 `us_etf_agent_data_alpaca.toml` 使用：

```toml
feed = "iex"
```

IEX 仅代表 IEX exchange 的成交，不应自动等同于 US consolidated market calendar / full-market daily observations。

对于正式 US ETF historical research，推荐优先验证：

```toml
feed = "sip"
```

Alpaca 官方说明：Historical endpoint 可通过 `feed=sip` 请求 SIP 数据；无 SIP 实时订阅时，历史查询的 `end` 需至少早于当前时间 15 分钟。具体 entitlement 仍以账户实际返回为准。

推荐策略：

```text
IEX -> smoke / connectivity / low-cost initial test
SIP -> primary historical research candidate
```

不得在 IEX 缺失时静默切换 SIP；feed 必须进入 request / manifest identity。

---

# 3. AKShare

## 3.1 接口状态

AKShare 为开源聚合库，FinAgent 当前用于：

```text
A-share daily smoke
US ETF secondary / cross-provider evidence
```

AKShare 不需要 API key，因此选择：

```toml
[market_data.profiles.akshare_free]
provider = "akshare"
```

时不读取 secret store。

安装：

```text
python -m pip install -e ".[cn-free]"
```

US ETF canonical provider-symbol mapping 已在：

```text
configs/markets/us_etf_agent_data_akshare.toml
```

显式配置，例如：

```toml
[market.provider_symbols]
SPY = "105.SPY"
QQQ = "105.QQQ"
IWM = "105.IWM"
DIA = "105.DIA"
```

拉取：

### Ubuntu

```bash
python scripts/pull_market_data.py \
  configs/markets/us_etf_agent_data_akshare.toml \
  --show-capabilities
```

### Windows PowerShell

```powershell
python scripts/pull_market_data.py `
  configs\markets\us_etf_agent_data_akshare.toml `
  --show-capabilities
```

注意：AKShare endpoint 与上游数据源可能变化，因此默认角色仍应是 smoke / secondary evidence，不应将 endpoint 可调用性误解为生产级 SLA。

---

# 4. Tushare Pro

## 4.1 接口状态

FinAgent 当前 `TushareMarketDataIngestor` 使用：

```text
equity -> pro.daily(...)
ETF    -> pro.fund_daily(...)
```

只支持 A-share equity / ETF daily bars。

Tushare 官方 Pro API 需要 token；不同接口还可能受积分、频次或独立 entitlement 限制。FinAgent 不应通过配置声明替代账户实际权限判断。

官方入口：

```text
https://tushare.pro/document/1?doc_id=40
https://tushare.pro/document/1?doc_id=37
```

## 4.2 获取 token

1. 注册并登录 Tushare Pro；
2. 在个人中心获取 Token；
3. 确认计划测试的 `daily` / `fund_daily` endpoint 对当前账户可用。

官方 Python SDK 也支持：

```python
pro = ts.pro_api("your token")
```

FinAgent 不要求调用者执行 `ts.set_token()`，而是在 host-side factory 中将 token 传入 `ts.pro_api(token)`。

## 4.3 FinAgent 配置

Public profile：

```toml
[market_data.profiles.tushare_optional]
provider = "tushare"
secret_id = "tushare"
```

Secret store：

```toml
[market_credentials.tushare]
token = "<Tushare Pro token>"
```

Canonical A-share ETF smoke config：

```text
configs/markets/a_share_etf_smoke.toml
```

执行：

### Ubuntu

```bash
python scripts/pull_market_data.py \
  configs/markets/a_share_etf_smoke.toml \
  --show-capabilities
```

### Windows PowerShell

```powershell
python scripts/pull_market_data.py `
  configs\markets\a_share_etf_smoke.toml `
  --show-capabilities
```

若 Tushare 返回 permission / points / quota error，应记录为 Provider entitlement evidence，不得自动 fallback 到 AKShare 或 HiThink。

---

# 5. HiThink / 同花顺金融数据 API

## 5.1 接口状态

FinAgent 当前 `HiThinkMarketDataIngestor` 使用官方 REST API：

```text
GET /api/a-share/prices/historical
header: X-api-key
interval: 1d
adjust: none
```

当前适合作为 A-share official daily-data candidate；代码没有宣称 minute/tick/Level-2 或 survivorship-bias-free delisted-history 能力。

官方文档：

```text
https://fuyao.aicubes.cn/docs/quickstart/
```

## 5.2 获取 API key

官方流程：

1. 使用同花顺账号登录文档站；
2. 进入 API Key 管理；
3. 创建 API Key；
4. REST 请求通过 `X-api-key: <your-api-key>` 鉴权。

官方错误语义包括：

```text
code=2001 -> API Key 缺失或无效
code=2003 -> 当前 API Key 无对应 capability 权限
```

## 5.3 FinAgent 配置

Public profile：

```toml
[market_data.profiles.hithink_official]
provider = "hithink"
secret_id = "hithink"
```

Secret store：

```toml
[market_credentials.hithink]
api_key = "<HiThink Finance API Key>"
```

Canonical smoke config：

```text
configs/markets/a_share_hithink_smoke.toml
```

执行：

### Ubuntu

```bash
python scripts/pull_market_data.py \
  configs/markets/a_share_hithink_smoke.toml \
  --show-capabilities
```

### Windows PowerShell

```powershell
python scripts/pull_market_data.py `
  configs\markets\a_share_hithink_smoke.toml `
  --show-capabilities
```

如果 API 返回 capability/permission error，应记录账户 entitlement，不得通过其它 Provider 自动替换。

---

# 6. Provider 测试矩阵

| Provider | Market | Credential | 当前 FinAgent 实际入口 | 测试角色 |
|---|---|---|---|---|
| Alpaca | US equity / ETF | API key + secret | historical stock bars | US primary candidate |
| AKShare | CN / US | 无 | `fund_etf_hist_em`, `stock_zh_a_hist`, `stock_us_hist` | smoke / secondary |
| Tushare | A-share | token | `daily`, `fund_daily` | optional reference |
| HiThink | A-share | API key | `/api/a-share/prices/historical` | official daily candidate |

每次 Provider 实测至少保存：

```text
profile name
provider
feed / endpoint
request date range
account entitlement result
row count
asset count
data_version
raw digest
normalized digest
quality report
```

---

# 7. DQ-10：fixed-universe session gap

## 7.1 错误含义

当前 `validate_records(..., require_common_calendar=True)` 对每个资产收集返回 bar 的 `event_time.date()`，然后：

```text
union_sessions = union(all asset sessions)
missing(asset) = union_sessions - asset_sessions
```

只要任一资产缺少 union 中的日期，就生成：

```text
DQ-10 fixed-universe asset ... is missing N sessions
```

因此 DQ-10 当前表示的是：

```text
Provider 返回的固定 universe bar calendar 不一致
```

它**不能单独证明**：

```text
真实交易所发生停牌
退市
ETF 未交易
```

也不能区分：

```text
provider feed coverage gap
provider outage
corporate-action/symbol issue
真实 tradability event
```

## 7.2 失败后诊断文件仍存在

`finalize_materialization()` 在 `quality.raise_if_failed()` 之前已经写出：

```text
raw_records.json
bars.csv
quality_report.json
manifest.json
```

因此 pull 报错后先不要删除输出目录，应先检查诊断证据。

Windows：

```powershell
Get-Content data\market\us_etf_alpaca\quality_report.json
```

Ubuntu：

```bash
cat data/market/us_etf_alpaca/quality_report.json
```

## 7.3 找出具体缺失日期

Windows / Ubuntu 均可使用：

```text
python -c "from collections import defaultdict; from finagent.data import read_normalized_csv; r=read_normalized_csv('data/market/us_etf_alpaca/bars.csv'); c=defaultdict(set); [c[x.asset.symbol].add(x.bar.event_time.date()) for x in r]; u=set().union(*c.values()); print({k:[str(d) for d in sorted(u-v)] for k,v in c.items() if u-v})"
```

对于错误：

```text
DIA missing 1
IWM missing 1
QQQ missing 1
SPY no error
```

含义是至少有一个 session date 只出现在 SPY 的返回数据中，而另外三只 ETF 没有对应 bar。

## 7.4 当前 Alpaca 场景的优先排查顺序

1. 记录具体缺失日期；
2. 确认当前 config 的 `feed`；
3. 若为 `iex`，用独立输出目录测试 `sip`；
4. 比较 IEX/SIP 的 rows、calendar 与 quality report；
5. 若 SIP 通过，则将问题归类为 IEX feed coverage / observation completeness，而不是资产停牌；
6. 若 SIP 仍失败，再核对交易所日历及 provider raw response。

建议不要直接使用：

```text
--allow-calendar-gaps
```

来使 primary research data 通过，因为这会绕过固定 universe calendar 异常，而不是解释异常。

---

# 8. 对 FinAgent 的推荐代码修改

## P0 / 当前测试前推荐

### A. 将 US research-grade Alpaca historical config 从 IEX 与 SIP 角色分离

推荐：

```text
alpaca_iex_smoke
alpaca_sip_primary
```

不要使用：

```text
feed = iex
provider_role = primary
```

这种语义组合。

正式 US ETF historical research 优先使用 SIP；IEX 保留连接性/smoke 测试。

### B. DQ-10 报告具体日期

当前错误只显示：

```text
missing 1 sessions
```

建议增加：

```text
missing_dates=[YYYY-MM-DD, ...]
provider
feed
```

至少显示前 N 个日期，并把完整日期列表写入 quality report。

### C. 修正 DQ-10 message

当前 message 直接提示：

```text
use Level 2 tradability semantics for suspensions/delistings
```

对 IEX coverage gap 容易产生误导。

建议改为：

```text
fixed-universe provider calendar gap; distinguish provider/feed coverage from tradability events before acceptance
```

## P1 / 后续增强

引入显式 calendar validation policy：

```text
STRICT_FIXED_UNIVERSE
WARN_PROVIDER_GAPS
TRADABILITY_AWARE
```

长期应使用明确的 exchange-session calendar + tradability semantics，而不是仅用 Provider 返回日期的 union 作为 expected calendar。

---

# 9. 当前验收原则

对于 primary research dataset：

```text
calendar gap -> investigate -> explain -> then accept/reject
```

不得采用：

```text
calendar gap -> silent intersection -> continue research
```

Provider 差异本身是 evidence；不得通过 silent fallback 抹去差异。
