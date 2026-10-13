import { type QueryClient } from "@tanstack/react-query";

import { type LarkIntegrationStatus } from "./types";

export const larkIntegrationQueryKey = ["integrations", "lark"] as const;

type LarkIntegrationQueryClient = Pick<
  QueryClient,
  "cancelQueries" | "setQueryData" | "invalidateQueries"
>;

function hasUnprobedRuntime(status: LarkIntegrationStatus): boolean {
  return !status.sandbox_runtime_probed;
}

export async function cacheLarkMutationStatus(
  queryClient: LarkIntegrationQueryClient,
  status: LarkIntegrationStatus,
): Promise<void> {
  // Await the cancel so an in-flight status read fully settles before the
  // mutation snapshot lands: a fire-and-forget cancel loses to a GET whose
  // fetch already resolved but whose cache write is still queued, and that
  // stale write would clobber the fresher mutation status.
  await queryClient.cancelQueries({ queryKey: larkIntegrationQueryKey });
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
  if (hasUnprobedRuntime(status)) {
    // Unprobed means the response came from a backend that predates the
    // field. The cancelled in-flight GET carried the authoritative runtime
    // fields, so refetch instead of risking the conservative fallback
    // lingering until the next focus/remount.
    void queryClient.invalidateQueries({ queryKey: larkIntegrationQueryKey });
  }
}
