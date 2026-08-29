import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useWorkbenchSse } from "./stream";
import type { AgentActiveRunProjectionV3 } from "./streamTypes";

class MockEventSource {
  static instances: MockEventSource[] = [];

  readonly url: string;
  readonly close = vi.fn();
  private readonly listeners = new Map<string, Set<EventListener>>();

  constructor(url: string | URL) {
    this.url = String(url);
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject | null) {
    if (!listener) return;
    const callback: EventListener =
      typeof listener === "function"
        ? listener
        : (event) => listener.handleEvent(event);
    const values = this.listeners.get(type) ?? new Set<EventListener>();
    values.add(callback);
    this.listeners.set(type, values);
  }

  removeEventListener(type: string, listener: EventListenerOrEventListenerObject | null) {
    if (!listener) return;
    const values = this.listeners.get(type);
    if (!values || typeof listener !== "function") return;
    values.delete(listener);
  }

  emit(type: string, data?: string) {
    const event = data === undefined
      ? new Event(type)
      : new MessageEvent(type, { data, lastEventId: "transport-id" });
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

const projection: AgentActiveRunProjectionV3 = {
  schema_version: "finagent.workbench.agent-active-run.v1",
  read_only: true,
  run_id: "run-stream",
  project_id: "project-stream",
  thread_id: "thread-stream",
  objective: "Stable Agent stream",
  actor: "research-agent",
  trigger_type: "research_program",
  status: "running",
  started_at: "2026-08-29T14:00:00+00:00",
  finished_at: null,
  updated_at: "2026-08-29T14:00:01+00:00",
  item_count: 1,
  artifact_count: 0,
  unresolved_artifact_count: 0,
  latest_activity: {
    item_id: "evt-1",
    item_type: "plan",
    occurred_at: "2026-08-29T14:00:00+00:00",
    title: "Run started",
    status: "started",
  },
  terminal: false,
  hidden_reasoning: "not_persisted_not_projected",
};

function Harness({
  enabled = true,
  onProjection,
}: {
  enabled?: boolean;
  onProjection?: (value: AgentActiveRunProjectionV3) => void;
}) {
  const stream = useWorkbenchSse<AgentActiveRunProjectionV3>({
    path: "/api/v3/streams/agent/runs/run-stream",
    eventType: "agent_run_snapshot",
    identity: "run-stream",
    enabled,
    onProjection: (value) => onProjection?.(value),
  });
  return (
    <div>
      <span data-testid="status">{stream.status}</span>
      <span data-testid="event-id">{stream.lastEventId}</span>
      <span data-testid="projection">{stream.lastProjection?.run_id ?? "none"}</span>
    </div>
  );
}

describe("V3-4 Workbench SSE client", () => {
  beforeEach(() => {
    MockEventSource.instances = [];
    vi.stubGlobal("EventSource", MockEventSource as unknown as typeof EventSource);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("opens one EventSource, accepts only the typed identity and closes on cleanup", () => {
    const onProjection = vi.fn();
    const view = render(<Harness onProjection={onProjection} />);
    expect(MockEventSource.instances).toHaveLength(1);
    const source = MockEventSource.instances[0];
    expect(source.url).toBe("/api/v3/streams/agent/runs/run-stream");
    expect(screen.getByTestId("status")).toHaveTextContent("connecting");

    act(() => source.emit("open"));
    expect(screen.getByTestId("status")).toHaveTextContent("open");

    act(() => {
      source.emit(
        "agent_run_snapshot",
        JSON.stringify({
          schema_version: "finagent.workbench.sse-event.v1",
          event_id: "agent-stream-event-1",
          event_type: "agent_run_snapshot",
          identity: "different-run",
          occurred_at: projection.updated_at,
          projection,
        }),
      );
    });
    expect(onProjection).not.toHaveBeenCalled();

    act(() => {
      source.emit(
        "agent_run_snapshot",
        JSON.stringify({
          schema_version: "finagent.workbench.sse-event.v1",
          event_id: "agent-stream-event-2",
          event_type: "agent_run_snapshot",
          identity: "run-stream",
          occurred_at: projection.updated_at,
          projection,
        }),
      );
    });
    expect(onProjection).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("event-id")).toHaveTextContent("agent-stream-event-2");
    expect(screen.getByTestId("projection")).toHaveTextContent("run-stream");

    act(() => source.emit("error"));
    expect(screen.getByTestId("status")).toHaveTextContent("reconnecting");

    view.unmount();
    expect(source.close).toHaveBeenCalledTimes(1);
  });

  it("does not construct EventSource when disabled", () => {
    render(<Harness enabled={false} />);
    expect(MockEventSource.instances).toHaveLength(0);
    expect(screen.getByTestId("status")).toHaveTextContent("disabled");
  });
});
