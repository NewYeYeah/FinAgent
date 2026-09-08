export const agentQueryKeys = {
  root: ["workbench2", "agent"] as const,
  projects: () => [...agentQueryKeys.root, "projects"] as const,
  project: (projectId: string) => [...agentQueryKeys.root, "project", projectId] as const,
  thread: (threadId: string) => [...agentQueryKeys.root, "thread", threadId] as const,
  run: (runId: string) => [...agentQueryKeys.root, "run", runId] as const,
  providerStatus: () => [...agentQueryKeys.root, "provider-status"] as const,
};
