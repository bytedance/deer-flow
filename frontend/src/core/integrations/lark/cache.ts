import { type QueryClient } from "@tanstack/react-query";

import { type LarkIntegrationStatus } from "./types";

export const larkIntegrationQueryKey = ["integrations", "lark"] as const;

type LarkIntegrationQueryClient = Pick<
  QueryClient,
  "cancelQueries" | "setQueryData"
>;

function hasUnprobedRuntime(status: LarkIntegrationStatus): boolean {
  return !status.sandbox_runtime_probed;
}

export function cacheLarkMutationStatus(
  queryClient: LarkIntegrationQueryClient,
  status: LarkIntegrationStatus,
): void {
  void queryClient.cancelQueries({ queryKey: larkIntegrationQueryKey });
  queryClient.setQueryData<LarkIntegrationStatus>(
    larkIntegrationQueryKey,
    (current) =>
      current && hasUnprobedRuntime(status)
        ? {
            ...status,
            sandbox_runtime_mode: current.sandbox_runtime_mode,
            sandbox_runtime_probed: current.sandbox_runtime_probed,
            sandbox_runtime_ready: current.sandbox_runtime_ready,
            sandbox_runtime_detail: current.sandbox_runtime_detail,
          }
        : status,
  );
}
