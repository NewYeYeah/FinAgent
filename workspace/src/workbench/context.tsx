import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useSearchParams } from "react-router-dom";

export interface WorkbenchContextState {
  project_id?: string;
  thread_id?: string;
  run_id?: string;
  program_id?: string;
  factor_id?: string;
  portfolio_validation_id?: string;
  strategy_id?: string;
  reserve_id?: string;
  asset_id?: string;
  date_range?: string;
  session_date?: string;
  fold_id?: string;
  environment?: string;
}

export type WorkbenchContextKey = keyof WorkbenchContextState;

export type WorkbenchInteractionEvent =
  | "project_selected"
  | "thread_selected"
  | "run_selected"
  | "asset_selected"
  | "date_range_selected"
  | "session_selected"
  | "factor_selected"
  | "order_selected"
  | "evidence_selected";

const CONTEXT_PARAM_BY_KEY: Record<WorkbenchContextKey, string> = {
  project_id: "project",
  thread_id: "thread",
  run_id: "run",
  program_id: "program",
  factor_id: "factor",
  portfolio_validation_id: "portfolio",
  strategy_id: "strategy",
  reserve_id: "reserve",
  asset_id: "asset",
  date_range: "range",
  session_date: "session",
  fold_id: "fold",
  environment: "env",
};

export const WORKBENCH_CONTEXT_KEYS = Object.keys(
  CONTEXT_PARAM_BY_KEY,
) as WorkbenchContextKey[];

function normalized(value: string | null | undefined): string | undefined {
  const result = value?.trim();
  return result ? result : undefined;
}

export function parseWorkbenchContext(
  params: URLSearchParams,
): WorkbenchContextState {
  const output: WorkbenchContextState = {};
  for (const key of WORKBENCH_CONTEXT_KEYS) {
    const value = normalized(params.get(CONTEXT_PARAM_BY_KEY[key]));
    if (value) output[key] = value;
  }
  return output;
}

export function serializeWorkbenchContext(
  current: URLSearchParams,
  context: WorkbenchContextState,
): URLSearchParams {
  const next = new URLSearchParams(current);
  for (const key of WORKBENCH_CONTEXT_KEYS) {
    next.delete(CONTEXT_PARAM_BY_KEY[key]);
  }
  for (const key of WORKBENCH_CONTEXT_KEYS) {
    const value = normalized(context[key]);
    if (value) next.set(CONTEXT_PARAM_BY_KEY[key], value);
  }
  return next;
}

export function workbenchContextSearch(context: WorkbenchContextState): string {
  const params = serializeWorkbenchContext(new URLSearchParams(), context);
  const value = params.toString();
  return value ? `?${value}` : "";
}

export function patchWorkbenchContext(
  current: WorkbenchContextState,
  patch: Partial<Record<WorkbenchContextKey, string | null | undefined>>,
): WorkbenchContextState {
  const next: WorkbenchContextState = { ...current };
  for (const key of WORKBENCH_CONTEXT_KEYS) {
    if (!(key in patch)) continue;
    const value = normalized(patch[key]);
    if (value) next[key] = value;
    else delete next[key];
  }
  return next;
}

interface WorkbenchContextValue {
  context: WorkbenchContextState;
  lastEvent: WorkbenchInteractionEvent | null;
  select: (
    patch: Partial<Record<WorkbenchContextKey, string | null | undefined>>,
    event: WorkbenchInteractionEvent,
    options?: { replace?: boolean },
  ) => void;
  clear: (options?: { replace?: boolean }) => void;
}

const WorkbenchContext = createContext<WorkbenchContextValue | null>(null);

export function WorkbenchContextProvider({ children }: { children: ReactNode }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [lastEvent, setLastEvent] = useState<WorkbenchInteractionEvent | null>(null);
  const context = useMemo(
    () => parseWorkbenchContext(searchParams),
    [searchParams],
  );

  const select = useCallback<WorkbenchContextValue["select"]>(
    (patch, event, options) => {
      const nextContext = patchWorkbenchContext(context, patch);
      const next = serializeWorkbenchContext(searchParams, nextContext);
      setLastEvent(event);
      setSearchParams(next, { replace: options?.replace ?? false });
    },
    [context, searchParams, setSearchParams],
  );

  const clear = useCallback<WorkbenchContextValue["clear"]>(
    (options) => {
      const next = serializeWorkbenchContext(searchParams, {});
      setLastEvent(null);
      setSearchParams(next, { replace: options?.replace ?? false });
    },
    [searchParams, setSearchParams],
  );

  const value = useMemo<WorkbenchContextValue>(
    () => ({ context, lastEvent, select, clear }),
    [clear, context, lastEvent, select],
  );

  return (
    <WorkbenchContext.Provider value={value}>
      {children}
    </WorkbenchContext.Provider>
  );
}

export function useWorkbenchContext(): WorkbenchContextValue {
  const value = useContext(WorkbenchContext);
  if (!value) {
    throw new Error("useWorkbenchContext must be used within WorkbenchContextProvider");
  }
  return value;
}
