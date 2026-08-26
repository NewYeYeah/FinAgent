# FinAgent 1.2.2 Development Risk Register

Date: 2026-08-26

## Development principle

FinAgent now uses a staged treatment for research-data leakage and governance risks.

The default rule is:

> Implement the minimum controls required to preserve numerical validity and irreversible public interfaces now; record lower-priority leakage and recovery risks explicitly; complete the functional research-to-paper workflow before returning for a dedicated hardening pass.

This replaces the previous tendency to treat every plausible leakage path as a release blocker during feature construction.

## Priority model

### P0 — block current development until fixed

A P0 issue invalidates research evidence, changes a frozen public contract, or allows normal production code to cross the development/OOS boundary directly.

Examples:

- look-ahead through `available_at` / event-time mistakes;
- train/validation/holdout time overlap in the canonical dataset contract;
- mutable experiment, dataset, strategy or holdout identities;
- reusing a sealed holdout after it has been consumed;
- selecting or tuning a final strategy using holdout metrics;
- ordinary Agent-visible memory exposing sealed-holdout results;
- inconsistent execution clock or cost protocol between development and final evaluation.

P0 controls stay in the critical development path.

### P1 — record now, harden after the functional chain is complete

A P1 issue can weaken information isolation or audit robustness, but does not invalidate the normal governed execution path under expected use.

Current P1 items:

1. Crash window after terminal holdout report persistence but before `ResearchProgram` reaches `CLOSED`.
   - Current behavior remains one-shot because holdout consumption is durable.
   - Desired hardening: lifecycle recovery may close the program without re-reading holdout data.

2. Development-data firewall against every possible low-level `DataAdapter` call site.
   - Current governed paths bind explicit development/holdout windows.
   - Desired hardening: capability/view objects that make out-of-scope time ranges unrequestable by construction.

3. Secondary registry/query paths that could accidentally surface sealed evidence outside adaptive Agent memory.
   - Current sealed evaluator uses a dedicated report store and scoped memory writer.
   - Desired hardening: repository-wide read-path audit and explicit visibility labels for all research result stores.

4. Process-level/operator leakage controls.
   - Current scope is application-code governance.
   - Desired hardening may include separate credentials/stores/processes for sealed datasets if a deployment requires stronger organizational isolation.

5. Research-to-paper handoff spans the research registry and paper operational store.
   - Normal path records immutable handoff identity, exact human approval, model-stage transition and operational application.
   - A process crash between writes can leave a partially applied cross-store transition even though each individual store remains durable.
   - Desired hardening: explicit reconciliation/recovery routine or a consolidated transaction boundary if operational use demonstrates the need.
   - Promote to P0 if partial handoff states are observed in routine operation or can authorize orders without a verifiable approval chain.

### P2 — defer unless deployment evidence makes it necessary

P2 covers theoretical, low-probability or infrastructure-level concerns whose mitigation would materially slow feature development without improving current research correctness.

Examples:

- adversarial side-channel leakage between local processes;
- cryptographic sealing/HSM-backed holdout access;
- physically separate research and validation infrastructure;
- generalized information-flow control across every plugin or future provider.

## Current acceptance rule

A new feature is not blocked merely because a plausible leakage scenario exists.

It is blocked only if the scenario is P0 according to the definitions above, or if the implementation would make a later fix require breaking the frozen numerical/public interfaces.

Every discovered P1/P2 issue should be added here with:

- affected component;
- failure mode;
- current containment;
- proposed hardening;
- trigger for promotion to P0.

## Functional priority after the current evaluator

After the one-shot sealed holdout evaluator passes CI, development priority moves to the remaining functional chain:

```text
sealed holdout report
        ↓
deterministic ResearchPromotionGate
        ↓
model/artifact promotion record
        ↓
paper/shadow execution handoff
        ↓
repeatable operational evaluation
```

A dedicated leakage/recovery hardening pass follows after this chain is executable end to end, unless a newly discovered P0 issue requires immediate interruption.
