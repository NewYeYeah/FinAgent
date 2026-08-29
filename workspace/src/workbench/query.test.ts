import { describe, expect, it } from "vitest";

import {
  WorkbenchQueryClient,
  serializeQueryKey,
  workbenchQueryKeys,
} from "./query";

describe("WorkbenchQueryClient", () => {
  it("deduplicates in-flight identity queries and reuses fresh cached data", async () => {
    const client = new WorkbenchQueryClient();
    const key = workbenchQueryKeys.agentRun("run-a");
    let calls = 0;
    let release: ((value: { run_id: string }) => void) | undefined;
    const queryFn = () => {
      calls += 1;
      return new Promise<{ run_id: string }>((resolve) => {
        release = resolve;
      });
    };

    const first = client.fetchQuery({ key, queryFn, staleTime: 60_000 });
    const second = client.fetchQuery({ key, queryFn, staleTime: 60_000 });
    expect(second).toBe(first);
    expect(calls).toBe(1);

    release?.({ run_id: "run-a" });
    await expect(first).resolves.toEqual({ run_id: "run-a" });

    await expect(
      client.fetchQuery({ key, queryFn, staleTime: 60_000 }),
    ).resolves.toEqual({ run_id: "run-a" });
    expect(calls).toBe(1);
  });

  it("invalidates one identity without flushing unrelated query state", async () => {
    const client = new WorkbenchQueryClient();
    const runA = workbenchQueryKeys.agentRun("run-a");
    const runB = workbenchQueryKeys.agentRun("run-b");
    let callsA = 0;
    let callsB = 0;

    await client.fetchQuery({
      key: runA,
      queryFn: async () => ({ run_id: "run-a", revision: ++callsA }),
      staleTime: 60_000,
    });
    await client.fetchQuery({
      key: runB,
      queryFn: async () => ({ run_id: "run-b", revision: ++callsB }),
      staleTime: 60_000,
    });

    client.invalidate(runA);

    await expect(
      client.fetchQuery({
        key: runA,
        queryFn: async () => ({ run_id: "run-a", revision: ++callsA }),
        staleTime: 60_000,
      }),
    ).resolves.toEqual({ run_id: "run-a", revision: 2 });
    await expect(
      client.fetchQuery({
        key: runB,
        queryFn: async () => ({ run_id: "run-b", revision: ++callsB }),
        staleTime: 60_000,
      }),
    ).resolves.toEqual({ run_id: "run-b", revision: 1 });

    expect(callsA).toBe(2);
    expect(callsB).toBe(1);
  });

  it("records synchronous query failures in the same error state", async () => {
    const client = new WorkbenchQueryClient();
    const key = workbenchQueryKeys.agentProject("project-error");

    await expect(
      client.fetchQuery({
        key,
        queryFn: () => {
          throw new Error("projection failed before Promise creation");
        },
      }),
    ).rejects.toThrow("projection failed before Promise creation");

    const snapshot = client.snapshot(serializeQueryKey(key));
    expect(snapshot.status).toBe("error");
    expect(snapshot.error).toBeInstanceOf(Error);
  });
});
