from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from finagent.domain.assets import AssetId, AssetType
from finagent.domain.execution import Fill
from finagent.domain.orders import OrderSide
from finagent.domain.portfolio import PortfolioState

from .domain import (
    BrokerOrderStatus,
    HumanApproval,
    KillSwitchSnapshot,
    KillSwitchStatus,
    OperationalApplication,
    PaperOrder,
)


def _asset_payload(asset: AssetId) -> dict[str, str]:
    return {
        "symbol": asset.symbol,
        "asset_type": asset.asset_type.value,
        "venue": asset.venue,
        "currency": asset.currency,
    }


def _asset_from(payload: Mapping[str, object]) -> AssetId:
    return AssetId(
        symbol=str(payload["symbol"]),
        asset_type=AssetType(str(payload["asset_type"])),
        venue=str(payload.get("venue", "")),
        currency=str(payload.get("currency", "USD")),
    )


def _dumps(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _paper_order_request(order: PaperOrder) -> dict[str, object]:
    return {
        "client_order_id": order.client_order_id,
        "asset": _asset_payload(order.asset),
        "side": order.side.value,
        "quantity": order.quantity,
        "submitted_at": order.submitted_at.isoformat(),
        "metadata": dict(order.metadata),
    }


def _paper_order_state(order: PaperOrder) -> dict[str, object]:
    return {
        **_paper_order_request(order),
        "updated_at": order.updated_at.isoformat(),
        "status": order.status.value,
        "filled_quantity": order.filled_quantity,
        "average_fill_price": order.average_fill_price,
        "commission": order.commission,
        "rejection_reason": order.rejection_reason,
    }


def _paper_order_from(payload: Mapping[str, object]) -> PaperOrder:
    return PaperOrder(
        client_order_id=str(payload["client_order_id"]),
        asset=_asset_from(payload["asset"]),
        side=OrderSide(str(payload["side"])),
        quantity=float(payload["quantity"]),
        submitted_at=datetime.fromisoformat(str(payload["submitted_at"])),
        updated_at=datetime.fromisoformat(str(payload["updated_at"])),
        status=BrokerOrderStatus(str(payload["status"])),
        filled_quantity=float(payload["filled_quantity"]),
        average_fill_price=float(payload["average_fill_price"]),
        commission=float(payload["commission"]),
        rejection_reason=str(payload.get("rejection_reason", "")),
        metadata=dict(payload.get("metadata", {})),
    )


def _fill_payload(fill: Fill) -> dict[str, object]:
    return {
        "client_order_id": fill.client_order_id,
        "asset": _asset_payload(fill.asset),
        "side": fill.side.value,
        "quantity": fill.quantity,
        "price": fill.price,
        "executed_at": fill.executed_at.isoformat(),
        "commission": fill.commission,
        "slippage": fill.slippage,
        "metadata": dict(fill.metadata),
    }


def _fill_from(payload: Mapping[str, object]) -> Fill:
    return Fill(
        client_order_id=str(payload["client_order_id"]),
        asset=_asset_from(payload["asset"]),
        side=OrderSide(str(payload["side"])),
        quantity=float(payload["quantity"]),
        price=float(payload["price"]),
        executed_at=datetime.fromisoformat(str(payload["executed_at"])),
        commission=float(payload["commission"]),
        slippage=float(payload["slippage"]),
        metadata=dict(payload.get("metadata", {})),
    )


def _state_payload(state: PortfolioState) -> dict[str, object]:
    return {
        "asof": state.asof.isoformat(),
        "base_currency": state.base_currency,
        "cash": state.cash,
        "positions": [
            {"asset": _asset_payload(asset), "quantity": quantity}
            for asset, quantity in sorted(state.positions.items())
        ],
        "marks": [
            {"asset": _asset_payload(asset), "price": price}
            for asset, price in sorted(state.marks.items())
        ],
    }


def _state_from(payload: Mapping[str, object]) -> PortfolioState:
    positions = {
        _asset_from(item["asset"]): float(item["quantity"])
        for item in payload.get("positions", [])
    }
    marks = {
        _asset_from(item["asset"]): float(item["price"])
        for item in payload.get("marks", [])
    }
    return PortfolioState(
        asof=datetime.fromisoformat(str(payload["asof"])),
        base_currency=str(payload["base_currency"]),
        cash=float(payload["cash"]),
        positions=positions,
        marks=marks,
    )


class SQLitePaperBrokerStore:
    """Durable paper-broker state with idempotent order/fill/account transitions."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.execute("PRAGMA foreign_keys = ON")
        return con

    def _initialize(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_orders (
                    client_order_id TEXT PRIMARY KEY,
                    request_json TEXT NOT NULL,
                    state_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_fills (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    fill_key TEXT NOT NULL UNIQUE,
                    client_order_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (client_order_id) REFERENCES paper_orders(client_order_id)
                );
                CREATE TABLE IF NOT EXISTS paper_account_snapshots (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_key TEXT NOT NULL UNIQUE,
                    asof TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS paper_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS applied_corporate_actions (
                    action_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operational_approvals (
                    approval_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operational_applications (
                    approval_id TEXT PRIMARY KEY,
                    request_type TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY (approval_id) REFERENCES operational_approvals(approval_id)
                );
                CREATE TABLE IF NOT EXISTS operational_state (
                    key TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                """
            )
            if con.execute("SELECT 1 FROM operational_state WHERE key='kill_switch'").fetchone() is None:
                initial = {
                    "status": KillSwitchStatus.ARMED.value,
                    "updated_at": datetime(1970, 1, 1, tzinfo=timezone.utc).isoformat(),
                    "reasons": [],
                    "actor": "system",
                }
                con.execute(
                    "INSERT INTO operational_state(key,payload_json) VALUES('kill_switch',?)",
                    (_dumps(initial),),
                )

    def record_event(self, event_type: str, occurred_at: datetime, payload: Mapping[str, object]) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO paper_events(event_type,occurred_at,payload_json) VALUES(?,?,?)",
                (event_type, occurred_at.isoformat(), _dumps(dict(payload))),
            )

    def list_events(self) -> tuple[dict[str, object], ...]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT event_type,occurred_at,payload_json FROM paper_events ORDER BY sequence"
            ).fetchall()
        return tuple(
            {"event_type": row[0], "occurred_at": row[1], "payload": json.loads(row[2])}
            for row in rows
        )

    def register_order(self, order: PaperOrder) -> PaperOrder:
        request_json = _dumps(_paper_order_request(order))
        state_json = _dumps(_paper_order_state(order))
        with self._connect() as con:
            row = con.execute(
                "SELECT request_json,state_json FROM paper_orders WHERE client_order_id=?",
                (order.client_order_id,),
            ).fetchone()
            if row is not None:
                if row[0] != request_json:
                    raise ValueError(f"client_order_id {order.client_order_id!r} was reused for a different order")
                return _paper_order_from(json.loads(row[1]))
            con.execute(
                "INSERT INTO paper_orders(client_order_id,request_json,state_json) VALUES(?,?,?)",
                (order.client_order_id, request_json, state_json),
            )
        self.record_event(
            "order_registered", order.submitted_at,
            {"client_order_id": order.client_order_id, "status": order.status.value},
        )
        return order

    def get_order(self, client_order_id: str) -> PaperOrder:
        with self._connect() as con:
            row = con.execute(
                "SELECT state_json FROM paper_orders WHERE client_order_id=?", (client_order_id,)
            ).fetchone()
        if row is None:
            raise KeyError(client_order_id)
        return _paper_order_from(json.loads(row[0]))

    def update_order(self, order: PaperOrder) -> None:
        with self._connect() as con:
            row = con.execute(
                "SELECT request_json FROM paper_orders WHERE client_order_id=?", (order.client_order_id,)
            ).fetchone()
            if row is None:
                raise KeyError(order.client_order_id)
            if row[0] != _dumps(_paper_order_request(order)):
                raise ValueError("order immutable request fields changed")
            con.execute(
                "UPDATE paper_orders SET state_json=? WHERE client_order_id=?",
                (_dumps(_paper_order_state(order)), order.client_order_id),
            )

    def list_open_orders(self) -> tuple[PaperOrder, ...]:
        with self._connect() as con:
            rows = con.execute("SELECT state_json FROM paper_orders ORDER BY client_order_id").fetchall()
        orders = tuple(_paper_order_from(json.loads(row[0])) for row in rows)
        return tuple(order for order in orders if not order.status.terminal)

    def has_fill(self, fill_key: str) -> bool:
        with self._connect() as con:
            return con.execute("SELECT 1 FROM paper_fills WHERE fill_key=?", (fill_key,)).fetchone() is not None

    def list_fills(self, client_order_id: str | None = None) -> tuple[Fill, ...]:
        with self._connect() as con:
            if client_order_id is None:
                rows = con.execute("SELECT payload_json FROM paper_fills ORDER BY sequence").fetchall()
            else:
                rows = con.execute(
                    "SELECT payload_json FROM paper_fills WHERE client_order_id=? ORDER BY sequence",
                    (client_order_id,),
                ).fetchall()
        return tuple(_fill_from(json.loads(row[0])) for row in rows)

    def save_account_snapshot(self, state: PortfolioState, *, snapshot_key: str) -> None:
        payload_json = _dumps(_state_payload(state))
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM paper_account_snapshots WHERE snapshot_key=?", (snapshot_key,)
            ).fetchone()
            if row is not None:
                if row[0] != payload_json:
                    raise ValueError(f"account snapshot {snapshot_key!r} is immutable")
                return
            con.execute(
                "INSERT INTO paper_account_snapshots(snapshot_key,asof,payload_json) VALUES(?,?,?)",
                (snapshot_key, state.asof.isoformat(), payload_json),
            )

    def latest_account_snapshot(self) -> PortfolioState:
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM paper_account_snapshots ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
        if row is None:
            raise KeyError("paper account has not been initialized")
        return _state_from(json.loads(row[0]))

    def has_account(self) -> bool:
        with self._connect() as con:
            return con.execute("SELECT 1 FROM paper_account_snapshots LIMIT 1").fetchone() is not None

    def apply_fill_transition(self, *, fill_key: str, fill: Fill, updated_order: PaperOrder, account: PortfolioState) -> bool:
        fill_json = _dumps(_fill_payload(fill))
        state_json = _dumps(_paper_order_state(updated_order))
        account_json = _dumps(_state_payload(account))
        snapshot_key = f"fill:{fill_key}"
        with self._connect() as con:
            if con.execute("SELECT 1 FROM paper_fills WHERE fill_key=?", (fill_key,)).fetchone():
                return False
            row = con.execute(
                "SELECT request_json FROM paper_orders WHERE client_order_id=?",
                (updated_order.client_order_id,),
            ).fetchone()
            if row is None:
                raise KeyError(updated_order.client_order_id)
            if row[0] != _dumps(_paper_order_request(updated_order)):
                raise ValueError("order immutable request fields changed")
            con.execute(
                "INSERT INTO paper_fills(fill_key,client_order_id,payload_json) VALUES(?,?,?)",
                (fill_key, fill.client_order_id, fill_json),
            )
            con.execute(
                "UPDATE paper_orders SET state_json=? WHERE client_order_id=?",
                (state_json, updated_order.client_order_id),
            )
            con.execute(
                "INSERT INTO paper_account_snapshots(snapshot_key,asof,payload_json) VALUES(?,?,?)",
                (snapshot_key, account.asof.isoformat(), account_json),
            )
            con.execute(
                "INSERT INTO paper_events(event_type,occurred_at,payload_json) VALUES(?,?,?)",
                (
                    "fill", fill.executed_at.isoformat(),
                    _dumps({
                        "fill_key": fill_key,
                        "client_order_id": fill.client_order_id,
                        "quantity": fill.quantity,
                        "price": fill.price,
                        "status": updated_order.status.value,
                    }),
                ),
            )
        return True

    def apply_corporate_action(self, *, action_id: str, payload: Mapping[str, object], state: PortfolioState) -> bool:
        action_json = _dumps(dict(payload))
        account_json = _dumps(_state_payload(state))
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM applied_corporate_actions WHERE action_id=?", (action_id,)
            ).fetchone()
            if row is not None:
                if row[0] != action_json:
                    raise ValueError(f"corporate action {action_id!r} is immutable")
                return False
            con.execute(
                "INSERT INTO applied_corporate_actions(action_id,payload_json) VALUES(?,?)",
                (action_id, action_json),
            )
            con.execute(
                "INSERT INTO paper_account_snapshots(snapshot_key,asof,payload_json) VALUES(?,?,?)",
                (f"corporate_action:{action_id}", state.asof.isoformat(), account_json),
            )
            con.execute(
                "INSERT INTO paper_events(event_type,occurred_at,payload_json) VALUES(?,?,?)",
                ("corporate_action", state.asof.isoformat(), action_json),
            )
        return True

    def get_kill_switch(self) -> KillSwitchSnapshot:
        with self._connect() as con:
            row = con.execute("SELECT payload_json FROM operational_state WHERE key='kill_switch'").fetchone()
        payload = json.loads(row[0])
        return KillSwitchSnapshot(
            status=KillSwitchStatus(payload["status"]),
            updated_at=datetime.fromisoformat(payload["updated_at"]),
            reasons=tuple(payload["reasons"]),
            actor=payload["actor"],
        )

    def set_kill_switch(self, snapshot: KillSwitchSnapshot) -> None:
        payload = {
            "status": snapshot.status.value,
            "updated_at": snapshot.updated_at.isoformat(),
            "reasons": list(snapshot.reasons),
            "actor": snapshot.actor,
        }
        with self._connect() as con:
            con.execute(
                "UPDATE operational_state SET payload_json=? WHERE key='kill_switch'", (_dumps(payload),)
            )
            con.execute(
                "INSERT INTO paper_events(event_type,occurred_at,payload_json) VALUES(?,?,?)",
                ("kill_switch", snapshot.updated_at.isoformat(), _dumps(payload)),
            )

    def record_approval(self, approval: HumanApproval) -> None:
        payload = {
            "approval_id": approval.approval_id,
            "request_type": approval.request_type,
            "snapshot_id": approval.snapshot_id,
            "approved_by": approval.approved_by,
            "approved_at": approval.approved_at.isoformat(),
            "policy_id": approval.policy_id,
            "reason": approval.reason,
        }
        encoded = _dumps(payload)
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM operational_approvals WHERE approval_id=?", (approval.approval_id,)
            ).fetchone()
            if row is not None:
                if row[0] != encoded:
                    raise ValueError(f"approval {approval.approval_id!r} is immutable")
                return
            con.execute(
                "INSERT INTO operational_approvals(approval_id,payload_json) VALUES(?,?)",
                (approval.approval_id, encoded),
            )

    def record_application(self, application: OperationalApplication) -> None:
        payload = {
            "approval_id": application.approval_id,
            "request_type": application.request_type,
            "snapshot_id": application.snapshot_id,
            "applied_at": application.applied_at.isoformat(),
            "applied_by": application.applied_by,
            "policy_id": application.policy_id,
            "mutation_performed": application.mutation_performed,
        }
        encoded = _dumps(payload)
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM operational_applications WHERE approval_id=?", (application.approval_id,)
            ).fetchone()
            if row is not None:
                if row[0] != encoded:
                    raise ValueError(f"application for approval {application.approval_id!r} is immutable")
                return
            con.execute(
                """INSERT INTO operational_applications
                   (approval_id,request_type,snapshot_id,policy_id,payload_json)
                   VALUES(?,?,?,?,?)""",
                (application.approval_id, application.request_type, application.snapshot_id, application.policy_id, encoded),
            )
            if application.request_type == "operating_policy":
                con.execute(
                    """INSERT INTO operational_state(key,payload_json) VALUES('operating_policy',?)
                       ON CONFLICT(key) DO UPDATE SET payload_json=excluded.payload_json""",
                    (_dumps({
                        "policy_id": application.policy_id,
                        "approval_id": application.approval_id,
                        "effective_at": application.applied_at.isoformat(),
                    }),),
                )
            if application.request_type == "rebalance":
                con.execute(
                    """INSERT INTO operational_state(key,payload_json) VALUES(?,?)
                       ON CONFLICT(key) DO UPDATE SET payload_json=excluded.payload_json""",
                    (
                        f"rebalance:{application.snapshot_id}",
                        _dumps({
                            "approval_id": application.approval_id,
                            "snapshot_id": application.snapshot_id,
                            "approved_at": application.applied_at.isoformat(),
                        }),
                    ),
                )

    def current_operating_policy(self) -> str | None:
        with self._connect() as con:
            row = con.execute("SELECT payload_json FROM operational_state WHERE key='operating_policy'").fetchone()
        return None if row is None else str(json.loads(row[0])["policy_id"])

    def rebalance_approval_id(self, snapshot_id: str) -> str | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT payload_json FROM operational_state WHERE key=?", (f"rebalance:{snapshot_id}",)
            ).fetchone()
        return None if row is None else str(json.loads(row[0])["approval_id"])
