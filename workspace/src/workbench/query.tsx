import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";

export type WorkbenchQueryKey = readonly (
  | string
  | number
  | boolean
  | null
  | undefined
)[];

type QueryStatus = "idle" | "pending" | "success" | "error";

interface QuerySnapshot<T> {
  status: QueryStatus;
  data?: T;
  error?: unknown;
  updatedAt: number;
  promise?: Promise<T>;
}

const IDLE_SNAPSHOT: QuerySnapshot<never> = {
  status: "idle",
  updatedAt: 0,
};

export function serializeQueryKey(key: WorkbenchQueryKey): string {
  return JSON.stringify(key);
}

export class WorkbenchQueryClient {
  private readonly entries = new Map<string, QuerySnapshot<unknown>>();
  private readonly listeners = new Map<string, Set<() => void>>();

  private emit(serializedKey: string) {
    for (const listener of this.listeners.get(serializedKey) ?? []) listener();
  }

  subscribe(serializedKey: string, listener: () => void): () => void {
    const current = this.listeners.get(serializedKey) ?? new Set<() => void>();
    current.add(listener);
    this.listeners.set(serializedKey, current);
    return () => {
      current.delete(listener);
      if (!current.size) this.listeners.delete(serializedKey);
    };
  }

  snapshot<T>(serializedKey: string): QuerySnapshot<T> {
    return (this.entries.get(serializedKey) ?? IDLE_SNAPSHOT) as QuerySnapshot<T>;
  }

  invalidate(key?: WorkbenchQueryKey) {
    if (!key) {
      this.entries.clear();
      for (const serializedKey of this.listeners.keys()) this.emit(serializedKey);
      return;
    }
    const serializedKey = serializeQueryKey(key);
    this.entries.delete(serializedKey);
    this.emit(serializedKey);
  }

  fetchQuery<T>({
    key,
    queryFn,
    staleTime = 30_000,
    force = false,
  }: {
    key: WorkbenchQueryKey;
    queryFn: () => Promise<T>;
    staleTime?: number;
    force?: boolean;
  }): Promise<T> {
    const serializedKey = serializeQueryKey(key);
    const current = this.snapshot<T>(serializedKey);
    if (!force && current.status === "success" && current.data !== undefined) {
      if (Date.now() - current.updatedAt <= staleTime) {
        return Promise.resolve(current.data);
      }
    }
    if (!force && current.status === "pending" && current.promise) {
      return current.promise;
    }

    const promise = Promise.resolve()
      .then(queryFn)
      .then((data) => {
        this.entries.set(serializedKey, {
          status: "success",
          data,
          updatedAt: Date.now(),
        });
        this.emit(serializedKey);
        return data;
      })
      .catch((error: unknown) => {
        this.entries.set(serializedKey, {
          status: "error",
          error,
          updatedAt: Date.now(),
        });
        this.emit(serializedKey);
        throw error;
      });

    this.entries.set(serializedKey, {
      status: "pending",
      data: current.data,
      updatedAt: current.updatedAt,
      promise,
    });
    this.emit(serializedKey);
    return promise;
  }
}

const QueryClientContext = createContext<WorkbenchQueryClient | null>(null);

export function WorkbenchQueryProvider({
  children,
  client,
}: {
  children: ReactNode;
  client?: WorkbenchQueryClient;
}) {
  const fallback = useMemo(() => new WorkbenchQueryClient(), []);
  return (
    <QueryClientContext.Provider value={client ?? fallback}>
      {children}
    </QueryClientContext.Provider>
  );
}

export function useWorkbenchQueryClient(): WorkbenchQueryClient {
  const client = useContext(QueryClientContext);
  if (!client) {
    throw new Error("useWorkbenchQueryClient must be used within WorkbenchQueryProvider");
  }
  return client;
}

export function useWorkbenchQuery<T>({
  key,
  queryFn,
  enabled = true,
  staleTime = 30_000,
}: {
  key: WorkbenchQueryKey;
  queryFn: () => Promise<T>;
  enabled?: boolean;
  staleTime?: number;
}) {
  const client = useWorkbenchQueryClient();
  const serializedKey = serializeQueryKey(key);
  const queryFnRef = useRef(queryFn);
  queryFnRef.current = queryFn;

  const subscribe = useCallback(
    (listener: () => void) => client.subscribe(serializedKey, listener),
    [client, serializedKey],
  );
  const getSnapshot = useCallback(
    () => client.snapshot<T>(serializedKey),
    [client, serializedKey],
  );
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  useEffect(() => {
    if (!enabled) return;
    void client
      .fetchQuery({ key, queryFn: () => queryFnRef.current(), staleTime })
      .catch(() => undefined);
  }, [client, enabled, serializedKey, staleTime]);

  const refetch = useCallback(
    () => client.fetchQuery({ key, queryFn: () => queryFnRef.current(), staleTime, force: true }),
    [client, serializedKey, staleTime],
  );

  return {
    data: snapshot.data,
    error: snapshot.error,
    isPending:
      enabled && snapshot.data === undefined &&
      (snapshot.status === "idle" || snapshot.status === "pending"),
    isFetching: enabled && snapshot.status === "pending",
    status: snapshot.status,
    refetch,
  };
}

export const workbenchQueryKeys = {
  agentProjects: () => ["agent-projects"] as const,
  agentProject: (projectId: string) => ["agent-project", projectId] as const,
  agentThread: (threadId: string) => ["agent-thread", threadId] as const,
  agentRun: (runId: string) => ["agent-run", runId] as const,
  evidence: (evidenceId: string) => ["evidence", evidenceId] as const,
  configSnapshot: (configId: string) => ["config-snapshot", configId] as const,
  commandRun: (commandRunId: string) => ["command-run", commandRunId] as const,
};
