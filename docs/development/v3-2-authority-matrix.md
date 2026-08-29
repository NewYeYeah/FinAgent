# V3-2 Command Authority Matrix

| Command | Level | Catalog | Application service | Generic Control execution |
| --- | --- | --- | --- | --- |
| `config.validate` | L0 | allowlisted | ready | enabled when local Control is running |
| `data.certify_local_ashare` | L0 | allowlisted | ready | enabled when local Control is running |
| `review.export_bundle` | L0 | allowlisted | ready | enabled when local Control is running |
| `research.run_development` | L1 | allowlisted | adapter required | disabled |
| `research.run_a2p6` | L1 | allowlisted | adapter required | disabled |
| `portfolio.run_a4` | L1 | allowlisted | adapter required | disabled |

Generic Control never includes L2/L3 commands. Production reserve, promotion, PAPER mutation, broker/order and live-capital operations require later dedicated governance services and are not represented as generic V3-2 executable commands.
