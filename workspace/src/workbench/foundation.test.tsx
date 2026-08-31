import {
  act,
  cleanup,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  MemoryRouter,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { useState } from "react";

import {
  WorkbenchContextProvider,
  useWorkbenchContext,
} from "./context";
import { useWorkbenchSse } from "./stream";
import type { CommandRunStreamProjectionV3 } from "./streamTypes";

class MockEventSource {
  static instances: MockEventSource[] = [];

  readonly url: string;
  readonly close = vi.fn();
  private readonly listeners = new Map<string, Set<EventListener>>();

  constructor(url: string | URL) {
    this.url = String(url);
    MockEventSource.instances.push(this);
  }

  addEventListener(
    type: string,
    listener: EventListenerOrEventListenerObject | null,
  ) {
    if (!listener) return;
    const callback: EventListener =
      typeof listener === "function"
        ? listener
        : (event) => listener.handleEvent(event);
    const values = this.listeners.get(type) ?? new Set<EventListener>();
    values.add(callback);
    this.listeners.set(type, values);
  }

  removeEventListener(
    type: string,
    listener: EventListenerOrEventListenerObject | null,
  ) {
    if (!listener || typeof listener !== "function") return;
    this.listeners.get(type)?.delete(listener);
  }

  emit(type: string, data?: string) {
    const event =
      data === undefined
        ? new Event(type)
        : new MessageEvent(type, { data, lastEventId: "transport-v35" });
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

function ContextHistoryHarness() {
  const { context, select } = useWorkbenchContext();
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <div>
      <output data-testid="context">{JSON.stringify(context)}</output>
      <output data-testid="location">{`${location.pathname}${location.search}`}</output>
      <button
        type="button"
        onClick={() =>
          select(
            { project_id: "project-a", run_id: "run-a" },
            "run_selected",
          )
        }
      >
        Select A
      </button>
      <button
        type="button"
        onClick={() =>
          select(
            { project_id: "project-b", run_id: "run-b" },
            "run_selected",
          )
        }
      >
        Select B
      </button>
      <button type="button" onClick={() => navigate(-1)}>
        Back
      </button>
      <button type="button" onClick={() => navigate(1)}>
        Forward
      </button>
    </div>
  );
}

const terminalProjection: CommandRunStreamProjectionV3 = {
  schema_version: "finagent.workbench.command-run-stream.v1",
  read_only: true,
  command_run_id: "command-run-v35",
  command_id: "config.validate",
  state: "succeeded",
  config_snapshot_id: "config-snapshot-v35",
  context: { project_id: "project-v35" },
  requested_by: "acceptance-user",
  started_at: "2026-08-30T00:00:00+08:00",
  finished_at: "2026-08-30T00:00:01+08:00",
  updated_at: "2026-08-30T00:00:01+08:00",
  result_status: "succeeded",
  evidence_ids: [],
  latest_event: {
    event_id: "event-v35",
    sequence: 3,
    event_type: "RUN_SUCCEEDED",
    state: "succeeded",
    occurred_at: "2026-08-30T00:00:01+08:00",
  },
  terminal: true,
};

function StreamLifecycleHarness() {
  const [active, setActive] = useState(true);
  const stream = useWorkbenchSse<CommandRunStreamProjectionV3>({
    path: "/api/v3/streams/command-runs/command-run-v35",
    eventType: "command_run_snapshot",
    identity: "command-run-v35",
    enabled: active,
    onProjection: (projection) => {
      if (projection.terminal) setActive(false);
    },
  });
  return (
    <div>
      <output data-testid="stream-status">{stream.status}</output>
      <output data-testid="stream-projection">
        {stream.lastProjection?.state ?? "none"}
      </output>
    </div>
  );
}

describe("V3-5 Workbench foundation acceptance", () => {
  beforeEach(() => {
    MockEventSource.instances = [];
    vi.stubGlobal("EventSource", MockEventSource as unknown as typeof EventSource);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("restores URL-backed WorkbenchContext through browser back and forward", async () => {
    render(
      <MemoryRouter initialEntries={["/widgets?surface=configs&env=research"]}>
        <WorkbenchContextProvider>
          <ContextHistoryHarness />
        </WorkbenchContextProvider>
      </MemoryRouter>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Select A" }));
    expect(screen.getByTestId("context")).toHaveTextContent("project-a");
    expect(screen.getByTestId("context")).toHaveTextContent("run-a");
    expect(screen.getByTestId("location")).toHaveTextContent("surface=configs");
    expect(screen.getByTestId("location")).toHaveTextContent("env=research");

    await userEvent.click(screen.getByRole("button", { name: "Select B" }));
    expect(screen.getByTestId("context")).toHaveTextContent("project-b");
    expect(screen.getByTestId("context")).toHaveTextContent("run-b");

    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    await waitFor(() =>
      expect(screen.getByTestId("context")).toHaveTextContent("project-a"),
    );
    expect(screen.getByTestId("context")).toHaveTextContent("run-a");

    await userEvent.click(screen.getByRole("button", { name: "Forward" }));
    await waitFor(() =>
      expect(screen.getByTestId("context")).toHaveTextContent("project-b"),
    );
    expect(screen.getByTestId("context")).toHaveTextContent("run-b");
    expect(screen.getByTestId("location")).toHaveTextContent("surface=configs");
  });

  it("closes the native EventSource when a terminal CommandRun disables streaming", async () => {
    render(<StreamLifecycleHarness />);
    expect(MockEventSource.instances).toHaveLength(1);
    const source = MockEventSource.instances[0];

    act(() => source.emit("open"));
    expect(screen.getByTestId("stream-status")).toHaveTextContent("open");

    act(() => {
      source.emit(
        "command_run_snapshot",
        JSON.stringify({
          schema_version: "finagent.workbench.sse-event.v1",
          event_id: "command-stream-v35-terminal",
          event_type: "command_run_snapshot",
          identity: "command-run-v35",
          occurred_at: terminalProjection.updated_at,
          projection: terminalProjection,
        }),
      );
    });

    await waitFor(() =>
      expect(screen.getByTestId("stream-status")).toHaveTextContent("disabled"),
    );
    expect(source.close).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("stream-projection")).toHaveTextContent("none");
  });
});
