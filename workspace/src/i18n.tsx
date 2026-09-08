import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type WorkbenchLocale = "en" | "zh-CN";
export const WORKBENCH_LOCALE_STORAGE_KEY = "finagent.workbench.locale";
export const HIGH_CONTRAST_THEME = "high-contrast-dark";

const zhCN = new Map<string, string>([
  ["Language", "语言"], ["Workbench Foundation", "Workbench 工作台"], ["Evidence Workspace", "证据工作区"],
  ["FinAgent Workbench modules", "FinAgent Workbench 模块"], ["Command Center", "指挥中心"], ["Cockpit", "驾驶舱"],
  ["Agent", "智能体"], ["Agent Runs", "智能体运行"], ["Experiments", "实验"], ["Research Graph", "研究图谱"],
  ["Market", "市场状态"], ["Market State", "市场状态"], ["Strategy", "策略"], ["Factors", "因子"],
  ["Portfolio", "组合"], ["Execution", "执行"], ["Risk", "风险"], ["Operations", "运维"], ["Evidence", "证据"],
  ["Governance", "治理"], ["Reserve", "储备"], ["Configuration", "配置"], ["Command Catalog", "命令目录"],
  ["Widget Catalog", "组件目录"], ["Live", "实盘"], ["Research", "研究"], ["planned", "规划中"],
  ["Context", "上下文"], ["No linked selection", "无关联选择"], ["Clear", "清除"], ["Config", "配置"], ["Commands", "命令"],
  ["Project", "项目"], ["Thread", "会话"], ["Run", "运行"], ["Experiment", "实验"], ["Compare", "对比"],
  ["Research cycle", "研究周期"], ["Graph node", "图节点"], ["Market model", "市场模型"], ["Program", "研究程序"],
  ["Factor", "因子"], ["Asset", "资产"], ["Order", "订单"], ["Range", "区间"], ["Session", "交易日"],
  ["Fold", "折"], ["Environment", "环境"], ["Evidence Plane", "证据平面"], ["GET-only", "仅 GET"],
  ["local Control connected", "本地 Control 已连接"], ["Control unavailable", "Control 不可用"], ["Inspector", "检查器"],
  ["Open the local governed Command Palette", "打开本地受治理命令面板"],
  ["Control Plane unavailable; start scripts/run_workbench_control.py", "Control Plane 不可用；scripts/run_workbench_control.py 仅提供历史 Control"],
  ["Configuration remains read-only; protocol edits require a future governed fork workflow", "配置保持只读；协议修改需要后续受治理的 fork 流程"],
  ["Evidence Plane is GET-only. The optional local Control Plane is separate and limited to reviewed L0/L1 application services; no Gate, reserve, promotion, PAPER, broker-order or live-capital authority.", "证据平面仅支持 GET。可选本地 Control Plane 与其分离，且仅限已审查的 L0/L1 应用服务；不具备 Gate、reserve、promotion、PAPER、券商下单或实盘资金权限。"],
  ["Loading evidence", "正在加载证据"], ["Evidence could not be loaded", "无法加载证据"], ["unknown", "未知"], ["derived", "派生展示"],
  ["Evidence catalog", "证据目录"], ["Research programs", "研究程序"], ["Evidence lineage", "证据血缘"], ["Identity and source", "身份与来源"],
  ["Research Workspace", "研究工作区"], ["Workbench-2 · Agent-first research", "Workbench-2 · 智能体优先研究"],
  ["Objective → persisted actions/results → explicit decision → evidence.", "目标 → 持久化操作/结果 → 显式决策 → 证据。"],
  ["Research objective / session", "研究目标 / 会话"], ["Development only", "仅限开发"], ["Set the research objective", "设置研究目标"],
  ["Describe the admitted hypothesis or comparison to investigate.", "描述要研究的已准入假设或比较。"], ["Starting…", "正在启动…"],
  ["Start bounded research run", "启动受限研究运行"], ["Checking provider admission…", "正在检查 provider 准入…"],
  ["Provider unavailable / not admitted", "Provider 不可用 / 未准入"], ["Research start denied", "研究启动被拒绝"], ["Research start failed", "研究启动失败"],
  ["Research run", "研究运行"], ["Factor proposal", "因子提案"], ["Factor validation", "因子验证"],
  ["Factor development evaluation", "因子开发评估"], ["Final candidate decision", "最终候选决策"], ["Explicit research decision", "显式研究决策"],
  ["MarketState inspection", "MarketState 检查"], ["Factor library inspection", "FactorLibrary 检查"], ["Factor inspection", "因子检查"],
  ["Factor set proposal", "因子集提案"], ["Allocator proposal", "分配器提案"], ["Portfolio evaluation", "组合评估"],
  ["Experiment comparison", "实验比较"], ["Lifecycle decision", "生命周期决策"], ["Literature inspection", "文献检查"],
  ["Trial history inspection", "试验历史检查"], ["Next evaluation intent", "下一评估意图"], ["Runtime admission", "运行时准入"],
  ["Latest admitted historical state", "最新已准入历史状态"], ["State unavailable", "状态不可用"],
  ["Tested retrospectively on historical development data. Not historically known / not independent evidence.", "在历史开发数据上回溯测试。并非当时已知信息 / 不是独立证据。"],
  ["Action failed", "操作失败"], ["Action rejected", "操作被拒绝"], ["Proposed now", "当前提出"], ["Visible-history cutoff", "可见历史截止"],
  ["No earlier actions", "无更早操作"], ["Development RankIC", "开发 RankIC"], ["available observations", "可用观测"], ["All trial outcomes", "全部试验结果"],
  ["Preferred allocator", "首选分配器"], ["Cost sensitivity · 0 / 1 / 5 / 10bp", "成本敏感性 · 0 / 1 / 5 / 10bp"],
  ["Experiments are not comparable; no ranking is provided.", "实验不可比较；不提供排名。"], ["Compatible source, folds, costs and execution policy.", "来源、折、成本与执行策略兼容。"],
  ["Next action", "下一操作"], ["Development artifact", "开发工件"], ["Action details", "操作详情"], ["Remaining budget", "剩余预算"],
  ["Budget / slot exhaustion", "预算 / 槽位耗尽"], ["Tool calls", "工具调用"], ["Evaluations", "评估次数"], ["Tokens", "Tokens"], ["Cost", "成本"],
  ["Current factor set", "当前因子集"], ["Not selected", "未选择"], ["No state inspected yet", "尚未检查状态"], ["Latest experiment", "最新实验"],
  ["No completed portfolio evaluation", "无已完成组合评估"], ["Explicit next decision", "显式下一决策"], ["No next action recorded", "未记录下一操作"],
  ["Development candidate", "开发候选"], ["None proposed", "未提出"], ["Authority", "权限边界"],
  ["Canonical accepted research evidence", "Canonical 已接受研究证据"], ["Accepted R4 terminal", "已接受 R4 终态"], ["No adaptive strategy candidate", "无自适应候选策略"],
  ["Completeness-driven terminal; not a negative-return claim.", "由完整性驱动的终态；并非负收益结论。"],
  ["No candidate identity exists and no AdaptiveStrategy is accepted.", "不存在候选身份，且没有 AdaptiveStrategy 被接受。"],
  ["Rejected actions", "被拒操作"], ["Observed slot terminal", "观测到的槽位终态"], ["Campaign attestation", "Campaign 证明"], ["Resource summary", "资源摘要"],
  ["Configuration identities", "配置身份"], ["evidence reference only · never recomputed in React", "仅作证据引用 · React 永不重算"],
  ["Workbench-2 · persisted trials", "Workbench-2 · 持久化试验"],
  ["Directly inspect and compare persisted R4 trial/evaluation results. React selects and renders; it does not calculate RankIC, PnL, allocator results or rankings.", "直接检查并比较持久化的 R4 试验/评估结果。React 只做选择和展示；不计算 RankIC、PnL、分配器结果或排名。"],
  ["server projection authoritative", "服务器投影为权威"], ["hidden reasoning excluded", "不包含隐藏推理"], ["Persisted attempts", "持久化尝试"], ["compare", "对比"],
  ["No persisted experiment attempt is available for this selection. No experiment identity is fabricated.", "当前选择没有可用的持久化实验尝试。不会伪造实验身份。"],
  ["Authoritative result", "权威结果"], ["no browser recomputation", "浏览器不重算"], ["Authoritative metrics are unavailable/incomplete for this persisted attempt.", "该持久化尝试的权威指标不可用或不完整。"],
  ["Metrics source", "指标来源"], ["Evaluation scope", "评估范围"], ["Outcome", "结果"], ["Error / rejection", "错误 / 拒绝"],
  ["Experiment / trial identity", "实验 / 试验身份"], ["Identity kind", "身份类型"], ["Hypothesis", "假设"], ["Factor set", "因子集"], ["Allocator", "分配器"],
  ["Provider / model / resource accounting", "Provider / 模型 / 资源核算"], ["Provider", "Provider"], ["Model", "模型"], ["Evaluation used", "已用评估"], ["Evaluation remaining", "剩余评估"],
  ["Agent final decision", "智能体最终决策"], ["Decision action", "决策操作"], ["Recommendation", "建议"], ["Decision", "决策"], ["Terminal", "终态"],
  ["Related canonical identities", "关联 canonical 身份"], ["Agent run", "智能体运行"], ["Persisted comparison", "持久化比较"], ["Comparison unavailable", "比较不可用"],
  ["Loading persisted research experiments", "正在加载持久化研究实验"], ["Loading experiment detail", "正在加载实验详情"], ["Experiment authority", "实验权限边界"],
  ["Selection", "选择"], ["Comparison", "比较"], ["Open Research Graph", "打开研究图谱"], ["Strategy / terminal", "策略 / 终态"],
  ["Workbench-2 · canonical lineage", "Workbench-2 · canonical 血缘"], ["Persisted identities only. Missing relationships remain unresolved; text and names are never used to guess lineage.", "仅使用持久化身份。缺失关系保持未解析；绝不使用文本或名称猜测血缘。"],
  ["React Flow presentation", "React Flow 展示"], ["no hidden reasoning", "不展示隐藏推理"], ["Lineage Inspector", "血缘检查器"], ["Selected node", "已选节点"], ["Unresolved lineage", "未解析血缘"], ["Open Experiments", "打开实验"],
  ["Workbench-2 · causal state evidence", "Workbench-2 · 因果状态证据"], ["MarketState unavailable", "MarketState 不可用"],
  ["This accepted completeness/reliability result does not imply MarketState is invalid.", "这个已接受的完整性/可靠性结果并不意味着 MarketState 无效。"],
  ["Model identity & fit window", "模型身份与拟合窗口"], ["Latest persisted snapshot", "最新持久化快照"], ["Causal feature/model contract", "因果特征/模型契约"],
  ["Historical state probabilities", "历史状态概率"], ["Observed state transitions", "观测状态转移"], ["Factor performance / allocation by MarketState", "按 MarketState 的因子表现 / 配置"],
  ["Factor Intelligence", "因子智能"], ["Lifecycle, causal state-conditioned development evidence, persisted allocator weights and research lineage.", "生命周期、因果状态条件开发证据、持久化分配器权重与研究血缘。"],
  ["GET-only · server authoritative", "仅 GET · 服务器为权威"], ["Lifecycle / hypothesis", "生命周期 / 假设"], ["Family", "因子族"], ["Mechanism", "机制"], ["Origin", "来源"],
  ["Provenance / Agent decisions", "来源追踪 / 智能体决策"], ["Global development metrics", "全局开发指标"], ["MarketState-conditioned metrics", "MarketState 条件指标"],
  ["Cost-sensitive economics", "成本敏感经济指标"], ["Similarity / novelty", "相似性 / 新颖性"], ["Persisted allocator weight history", "持久化分配器权重历史"], ["Canonical linked research", "Canonical 关联研究"],
  ["Linked strategy analytics", "关联策略分析"], ["Loading linked research/strategy evidence", "正在加载关联研究/策略证据"],
  ["Workbench-2 · linked strategy analytics", "Workbench-2 · 关联策略分析"], ["No accepted R4 cycle is uniquely selected", "未唯一选择已接受的 R4 周期"], ["Accepted R4 terminal", "已接受 R4 终态"],
  ["no candidate", "无候选"], ["complete deterministic strategies", "完整确定性策略"], ["rejected Agent actions", "被拒智能体操作"],
  ["Accepted completeness/reliability evidence does not contain an AdaptiveStrategy candidate.", "已接受的完整性/可靠性证据不包含 AdaptiveStrategy 候选。"],
  ["This does not mean all strategies lost money, MarketState failed, or Agent value was proven negative.", "这并不意味着所有策略都亏损、MarketState 失败，或智能体价值已被证明为负。"],
  ["Persisted R4 development candidate", "持久化 R4 开发候选"], ["Strategy evidence", "策略证据"], ["Portfolio / execution", "组合 / 执行"], ["Execution / PnL", "执行 / PnL"], ["Attribution", "归因"],
  ["Strategy Decision Explorer", "策略决策浏览器"], ["Signal → target → order → fill → realized PnL", "信号 → 目标 → 订单 → 成交 → 已实现 PnL"],
  ["Open A4 cockpit", "打开 A4 驾驶舱"], ["No session selected", "未选择交易日"], ["Alpha rank", "Alpha 排名"], ["Expected return", "预期收益"],
  ["Target / realized", "目标 / 已实现"], ["Gross / net PnL", "毛 / 净 PnL"], ["Fees / slippage", "费用 / 滑点"], ["Execution status", "执行状态"],
  ["Portfolio Interactive Pack", "组合交互分析"], ["Execution Interactive Pack", "执行交互分析"], ["Portfolio evidence unavailable", "组合证据不可用"],
]);

function normalizeLocale(value: string | null | undefined): WorkbenchLocale { return value === "zh-CN" ? "zh-CN" : "en"; }
export function translateWorkbenchCopy(value: string, locale: WorkbenchLocale): string { return locale === "zh-CN" ? (zhCN.get(value) ?? value) : value; }

interface I18nValue { locale: WorkbenchLocale; t: (value: string) => string; setLocale: (locale: WorkbenchLocale) => void; }
const fallback: I18nValue = { locale: "en", t: (value) => value, setLocale: () => undefined };
const I18nContext = createContext<I18nValue>(fallback);

export function WorkbenchI18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<WorkbenchLocale>(() => typeof window === "undefined" ? "en" : normalizeLocale(window.localStorage.getItem(WORKBENCH_LOCALE_STORAGE_KEY)));
  useEffect(() => {
    document.documentElement.lang = locale;
    document.documentElement.dataset.theme = HIGH_CONTRAST_THEME;
    document.documentElement.style.colorScheme = "dark";
    window.localStorage.setItem(WORKBENCH_LOCALE_STORAGE_KEY, locale);
  }, [locale]);
  const setLocale = useCallback((next: WorkbenchLocale) => setLocaleState(normalizeLocale(next)), []);
  const t = useCallback((value: string) => translateWorkbenchCopy(value, locale), [locale]);
  const context = useMemo(() => ({ locale, t, setLocale }), [locale, setLocale, t]);
  return <I18nContext.Provider value={context}>{children}</I18nContext.Provider>;
}

export function useWorkbenchI18n(): I18nValue { return useContext(I18nContext); }

export function LocaleToggle() {
  const { locale, setLocale, t } = useWorkbenchI18n();
  return <div className="locale-toggle" role="group" aria-label={t("Language")} data-testid="locale-toggle">
    <button type="button" aria-pressed={locale === "en"} onClick={() => setLocale("en")}>EN</button>
    <button type="button" aria-pressed={locale === "zh-CN"} onClick={() => setLocale("zh-CN")}>中文</button>
  </div>;
}

export function PersistedTerminalLabel({ value }: { value: string }) {
  const { t } = useWorkbenchI18n();
  if (value !== "NO_ADAPTIVE_CANDIDATE") return <code>{value}</code>;
  return <span className="persisted-terminal-label"><span>{t("No adaptive strategy candidate")}</span><span aria-hidden="true">·</span><code>{value}</code></span>;
}
