import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { R4TerminalSummary } from "./researchTerminal";

afterEach(cleanup);

it("renders accepted negative R4 state without inventing a candidate or authority", () => {
  render(<R4TerminalSummary />);
  const terminal = screen.getByRole("region", { name: "Accepted R4 terminal" });
  for (const text of ["NO_ADAPTIVE_CANDIDATE", "AgentValue INCONCLUSIVE", "NONE", "NOT STARTED", "NOT CONFIRMED", "NOT ACCEPTED", "NOT AUTHORIZED", "SLOT_ATTEMPTS_EXHAUSTED"]) {
    expect(within(terminal).getByText(text)).toBeVisible();
  }
  expect(within(terminal).getByText(/No candidate identity exists/)).toBeVisible();
  expect(within(terminal).getByText(/not a negative-return claim/)).toBeVisible();
  expect(within(terminal).getByRole("link", { name: "Campaign attestation" })).toHaveAttribute("href", expect.stringContaining("campaign_result_attestation.json"));
  expect(within(terminal).queryByText(/chain-of-thought/i)).not.toBeInTheDocument();
});
