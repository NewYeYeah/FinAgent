# US-R2 final multi-regime Alpha Gate

US-R2 closes the denominator-preserving multi-regime replication. The final Gate consumes only the reviewed row-free/compact evidence produced by US-R2-2a through US-R2-2c2; it does not reopen minute data, recompute candidates or alter the frozen denominator.

## Frozen inputs

The final evidence chain binds:

- frozen protocol `us-r2-frozen-protocol-13f55d77124730249454e769`;
- complete 37-candidate denominator `us-r1-denominator-be5184ac3883b0799c00c5dc`;
- primary fold-regime report `us-r2-primary-statistics-39329ed645222038a8e29fef`;
- pooled inference report `us-r2-pooled-inference-a0a2e40c2ec246fc607fab92`;
- candidate robustness report `us-r2-candidate-robustness-9b8a0b575e20e31e6adc9ddf`.

Every candidate must retain exactly five folds by four regimes, or 20 primary cells. Pooled HAC, session-block bootstrap, Holm and BH evidence must use all 37 candidates. Frequency and decay robustness must retain all four regimes.

## Gate policy

`canonical_us_r2_alpha_gate_policy()` inherits every numeric threshold from R1 policy `us-r1-alpha-gate-policy-92c02d52e0b6227daaf8da4c`:

- primary RankIC, worst-cell RankIC, mean/worst ICIR and positive-cell ratio;
- raw HAC, Holm, BH, session-block bootstrap and confidence interval;
- the strict `2/3` frequency and decay sign rules, required separately in every regime;
- coverage, quantile monotonicity, gross long-short return, turnover and return per turnover.

The only structural adaptation is evaluating the frozen 20 fold-regime cells rather than the R1 three-fold layout. No observed result can relax a threshold, remove a candidate or refit direction.

## Deterministic assembly

```powershell
python scripts/assemble_us_r2_alpha_evidence.py
```

The command content-validates all three source report IDs and their shared denominator, policy and lineage. It writes immutable policy, final family evidence, assessment and inference graph files under `reports/us_r2/final/`.

## Independent review

```powershell
python scripts/review_us_r2_alpha_gate.py `
  --reviewer-id <reviewer> `
  --reviewed-at <timezone-aware-ISO-8601> `
  --review-notes <notes>
```

The reviewer independently reconstructs every final artifact and requires byte-equivalent JSON content before accepting the deterministic terminal. A review may accept the machine terminal or downgrade it to `SYSTEM_FAILURE`; it cannot upgrade a negative result.

## Reviewed result

The real 2006–2026 run produced:

```text
candidate count                         37
fold × regime cells per candidate      5 × 4 = 20
frequency/decay robust candidates      16
complete Alpha Gate robust candidates   0
technical blockers                      0
terminal                                NO_ROBUST_FACTOR_FAMILY
```

Review `us-r2-alpha-gate-review-36d4d07f8dd0b3dbf70656de` and manifest `us-r2-reviewed-evidence-b9c139214723c54e250d7ab6` establish terminal Alpha-Gate review authority. They do not establish Alpha authority because no candidate passed.

US-R2 therefore closes as a valid negative research result. It does not authorize US-X0 progression, execution, orders, PAPER or live capital. The fixed current-symbol EngineeringUniverse also remains survivorship conditioned and is not a PIT market-Alpha claim.
