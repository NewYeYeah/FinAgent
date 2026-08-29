import { useEffect, useRef, useState } from "react";

import { workspaceEventSourceUrl } from "../api";
import type {
  WorkbenchSseEventType,
  WorkbenchSseEventV3,
  WorkbenchSseStatus,
} from "./streamTypes";

export function useWorkbenchSse<TProjection>({
  path,
  eventType,
  identity,
  enabled = true,
  onProjection,
}: {
  path: string;
  eventType: WorkbenchSseEventType;
  identity: string;
  enabled?: boolean;
  onProjection?: (projection: TProjection, event: WorkbenchSseEventV3<TProjection>) => void;
}) {
  const callbackRef = useRef(onProjection);
  callbackRef.current = onProjection;
  const [status, setStatus] = useState<WorkbenchSseStatus>(
    enabled ? "connecting" : "disabled",
  );
  const [lastEventId, setLastEventId] = useState("");
  const [lastProjection, setLastProjection] = useState<TProjection | null>(null);

  useEffect(() => {
    if (!enabled || !path || !identity) {
      setStatus("disabled");
      setLastEventId("");
      setLastProjection(null);
      return;
    }
    if (typeof EventSource === "undefined") {
      setStatus("unavailable");
      return;
    }

    setStatus("connecting");
    const source = new EventSource(workspaceEventSourceUrl(path));

    const open = () => setStatus("open");
    const error = () => setStatus("reconnecting");
    const message = (raw: Event) => {
      const event = raw as MessageEvent<string>;
      try {
        const envelope = JSON.parse(event.data) as WorkbenchSseEventV3<TProjection>;
        if (envelope.event_type !== eventType || envelope.identity !== identity) return;
        setLastEventId(envelope.event_id || event.lastEventId || "");
        setLastProjection(envelope.projection);
        callbackRef.current?.(envelope.projection, envelope);
      } catch {
        // Invalid transport payload is ignored. It is never promoted to product state.
      }
    };

    source.addEventListener("open", open);
    source.addEventListener("error", error);
    source.addEventListener(eventType, message);

    return () => {
      source.removeEventListener("open", open);
      source.removeEventListener("error", error);
      source.removeEventListener(eventType, message);
      source.close();
    };
  }, [enabled, eventType, identity, path]);

  return { status, lastEventId, lastProjection };
}
