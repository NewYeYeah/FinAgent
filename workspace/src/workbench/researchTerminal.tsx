import "./research.css";

const BASELINE_SHA = "37a11cc246b96e7bbe1742bbee315c7b36d92c89";
const RESULT_ROOT = `https://github.com/NewYeYeah/FinAgent/blob/${BASELINE_SHA}/configs/research/r4_matched_v3_result`;

export const R4_ACCEPTED_TERMINAL = {
  reviewDisposition: "R4_RESULT_ACCEPTED",
  terminal: "NO_ADAPTIVE_CANDIDATE",
  agentValue: "INCONCLUSIVE",
  adaptiveStrategy: "NONE",
  r5: "NOT STARTED",
  alpha: "NOT CONFIRMED",
  paper: "NOT ACCEPTED",
  live: "NOT AUTHORIZED",
  candidateId: null,
  rejectedActionAttempts: 62,
  slotTerminal: "SLOT_ATTEMPTS_EXHAUSTED",
  interpretation: "Completeness-driven terminal; not a negative-return claim.",
  attestationUrl: `${RESULT_ROOT}/campaign_result_attestation.json`,
  resourceSummaryUrl: `${RESULT_ROOT}/resource_summary.json`,
} as const;

export function R4TerminalSummary() {
  const value = R4_ACCEPTED_TERMINAL;
  return (
    <section className="research-terminal" aria-label="Accepted R4 terminal">
      <header>
        <div>
          <span className="eyebrow">Canonical accepted research evidence</span>
          <h2>{value.terminal}</h2>
        </div>
        <span className="research-negative-pill">AgentValue {value.agentValue}</span>
      </header>
      <p>{value.interpretation} No candidate identity exists and no AdaptiveStrategy is accepted.</p>
      <dl className="research-terminal-grid">
        <div><dt>AdaptiveStrategy</dt><dd>{value.adaptiveStrategy}</dd></div>
        <div><dt>R5</dt><dd>{value.r5}</dd></div>
        <div><dt>Alpha</dt><dd>{value.alpha}</dd></div>
        <div><dt>PAPER</dt><dd>{value.paper}</dd></div>
        <div><dt>Live</dt><dd>{value.live}</dd></div>
        <div><dt>Rejected actions</dt><dd>{value.rejectedActionAttempts}</dd></div>
        <div><dt>Observed slot terminal</dt><dd className="mono">{value.slotTerminal}</dd></div>
      </dl>
      <div className="research-terminal-links">
        <a href={value.attestationUrl}>Campaign attestation</a>
        <a href={value.resourceSummaryUrl}>Resource summary</a>
        <a href="/widgets?surface=configs">Configuration identities</a>
      </div>
      <small>{value.reviewDisposition} · evidence reference only · never recomputed in React</small>
    </section>
  );
}
