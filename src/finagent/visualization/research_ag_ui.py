"""AG-UI SDK events inside the existing resumable Workbench SSE snapshot.

This is a thin event projection, not a new AG-UI backend or transport runtime.
Only explicit persisted actions are mapped; reasoning/raw events are absent.
"""

from __future__ import annotations

import json
from typing import Any

from finagent.visualization.agent_projection import AgentRunProjection


def research_ag_ui_events(run: AgentRunProjection) -> tuple[dict[str, Any], ...]:
    if run.governance.get("controller") != "r4":
        return ()
    from ag_ui.core import (
        RunErrorEvent,
        RunFinishedEvent,
        RunStartedEvent,
        StateSnapshotEvent,
        ToolCallArgsEvent,
        ToolCallEndEvent,
        ToolCallResultEvent,
        ToolCallStartEvent,
    )
    from ag_ui.encoder import EventEncoder

    events: list[Any] = [RunStartedEvent(thread_id=run.thread_id, run_id=run.run_id)]
    seen: set[str] = set()
    for item in run.items:
        tool = item.metadata.get("research_tool")
        if not isinstance(tool, dict) or item.call_id in seen:
            continue
        seen.add(item.call_id)
        events.extend(
            (
                ToolCallStartEvent(tool_call_id=item.call_id, tool_call_name=tool["tool"]),
                ToolCallArgsEvent(
                    tool_call_id=item.call_id, delta=json.dumps(tool["arguments"], sort_keys=True)
                ),
                ToolCallEndEvent(tool_call_id=item.call_id),
            )
        )
        if tool["result"] is not None:
            events.append(
                ToolCallResultEvent(
                    tool_call_id=item.call_id,
                    message_id=item.call_id + "-result",
                    content=json.dumps(
                        {"result": tool["result"], "policy": tool["policy"]}, sort_keys=True
                    ),
                )
            )
    events.append(StateSnapshotEvent(snapshot=dict(run.research)))
    if run.finished_at:
        events.append(
            RunFinishedEvent(
                thread_id=run.thread_id, run_id=run.run_id, result=run.research.get("candidate")
            )
            if run.status == "completed"
            else RunErrorEvent(message=run.error or run.status)
        )
    encoder = EventEncoder()
    # Keep the SDK's public aliases/serialization. Workbench remains responsible
    # for named snapshots, event IDs and Last-Event-ID reconciliation.
    return tuple(
        json.loads(encoder.encode(event).removeprefix("data: ").strip()) for event in events
    )
