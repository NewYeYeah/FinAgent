# MT5 PAPER replay implementation acceptance checklist

This checklist is implementation-only. It is not project-stage authority.

The increment is ready to merge only when all of the following are true:

- exact-command retry emits no second order or broker event;
- conflicting reuse of one `client_order_id` fails closed;
- duplicate `broker_deal_id` is idempotent only when content is identical;
- partial and full fills produce canonical trade/order lifecycle events;
- broker reject, cancel and expire are terminal and deterministic;
- stale/future/missing quotes reject before acknowledgement;
- per-order notional, gross notional and daily-loss guards reject before acknowledgement;
- kill switch rejects new commands and writes an incident record;
- normal broker snapshot versus RT projection reconciles to `CONSISTENT`;
- observable state mismatch reconciles to `DRIFT`;
- unavailable required broker/account state reconciles to `UNKNOWN`;
- JSONL recovery reproduces pre-restart broker snapshot and event identities;
- recovered exact command retry remains idempotent;
- source files contain no MT5 mutation surface;
- focused tests, deterministic smoke, Ruff, `mypy --strict`, `py_compile`, generic tests and docs governance all pass;
- `docs/status.toml` is unchanged.
