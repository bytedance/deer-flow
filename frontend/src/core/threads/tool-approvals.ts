import { useQuery } from "@tanstack/react-query";
import { useContext } from "react";

import { fetch } from "@/core/api/fetcher";
import { AuthQueryScopeContext } from "@/core/auth/query-scope";
import { getBackendBaseURL } from "@/core/config";
import { fetchFeatures } from "@/core/features/api";
import {
  extractHitlApprovalRequests,
  type HitlApprovalRequest,
  type HitlApprovalResponse,
} from "@/core/messages/human-input";

export type ApprovalMode = "ask" | "auto" | "full";

export function useToolApprovalFeature(enabled = true) {
  const account = useContext(AuthQueryScopeContext);
  return useQuery({
    queryKey: ["features", "tool_approval", account],
    queryFn: async () => (await fetchFeatures()).tool_approval ?? null,
    enabled,
    retry: false,
    staleTime: 60_000,
  });
}

export const approvalsKey = (threadId: string, account: unknown) =>
  ["tool-approvals", account, threadId] as const;

async function checked(response: Response) {
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const detail =
      body && typeof body === "object" && "detail" in body ? body.detail : null;
    throw new Error(
      typeof detail === "string"
        ? detail
        : `Approval request failed (${response.status})`,
    );
  }
  return response;
}

export async function fetchToolApprovals(
  threadId: string,
  signal?: AbortSignal,
) {
  const response = await checked(
    await fetch(
      `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/tool-approvals`,
      { signal },
    ),
  );
  const body = (await response.json()) as {
    requests?: unknown;
    grants?: unknown[];
  };
  return {
    requests: extractHitlApprovalRequests(body.requests),
    grantCount: Array.isArray(body.grants) ? body.grants.length : 0,
  };
}

export async function submitLiveApproval(
  threadId: string,
  request: HitlApprovalRequest,
  responses: HitlApprovalResponse[],
) {
  if (!request.run_id || request.transport !== "live")
    throw new Error("Missing live approval identity");
  await checked(
    await fetch(
      `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(request.run_id)}/tool-approvals/${encodeURIComponent(request.request_id)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ responses }),
      },
    ),
  );
}

export async function revokeThreadGrants(threadId: string) {
  await checked(
    await fetch(
      `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/tool-approvals/grants`,
      { method: "DELETE" },
    ),
  );
}

export function combineNativeApprovals(
  requests: HitlApprovalRequest[],
): HitlApprovalRequest[] {
  if (requests.length < 2) return requests;
  const first = requests[0]!;
  return [
    {
      ...first,
      actions: requests.flatMap((request) => request.actions),
      pending_tool_call_ids: requests.flatMap(
        (request) => request.pending_tool_call_ids,
      ),
      allowed_decisions: first.allowed_decisions.filter((decision) =>
        requests.every((request) =>
          request.allowed_decisions.includes(decision),
        ),
      ),
    },
  ];
}
