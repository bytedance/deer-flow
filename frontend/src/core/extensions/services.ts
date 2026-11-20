import { getAPIClient } from "@/core/api";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";
import { formatThreadAsJSON } from "@/core/threads/export";
import type { AgentThreadState } from "@/core/threads/types";
import { pathOfThread } from "@/core/threads/utils";

import type {
  ConversationActionContext,
  FrontendContribution,
  FrontendServices,
  ExtensionRequestOptions,
} from "./contracts";

/** Same Gateway and CSRF transport as host calls; never replay an HTTP mutation. */
export async function requestExtensionRoute(
  path: string,
  options: ExtensionRequestOptions = {},
  signal: AbortSignal,
  viewerId: string,
): Promise<Response> {
  signal.throwIfAborted();
  if (!viewerId) throw new Error("Reload this extension to bind its viewer");
  // Decode once for validation only; forward the original encoded resource IDs.
  const decoded = decodeURIComponent(path.split("?")[0]!);
  if (
    !decoded.startsWith("/api/extensions/") ||
    /[\\\\#\u0000-\u0020]/.test(path) ||
    decoded.split("/").some((part) => part === "." || part === "..") ||
    decoded.includes("\\") ||
    decoded.includes("%")
  )
    throw new Error("Expected a contributed extension route");
  const headers = new Headers(options.headers);
  headers.set("X-Deerflow-Plugin-Viewer", viewerId);
  const response = await fetch(`${getBackendBaseURL()}${path}`, {
    ...options,
    headers,
    signal: options.signal ? AbortSignal.any([signal, options.signal]) : signal,
    redirect: "error",
  });
  signal.throwIfAborted();
  return response;
}

export type HostServices = Omit<FrontendServices, "callBackend">;

/** Namespace comes from the installed page snapshot, never from action input. */
export function bindFrontendServices(
  base: HostServices,
  entry: FrontendContribution,
  signal?: AbortSignal,
): FrontendServices {
  return {
    ...base,
    async callBackend(action, payload) {
      if (!entry.backend_actions?.includes(action))
        throw new Error("Backend action not declared by this plugin");
      const response = await fetch(
        `${getBackendBaseURL()}/api/plugins/${encodeURIComponent(entry.namespace)}/actions/${encodeURIComponent(action)}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(entry.viewer_id
              ? { "X-Deerflow-Plugin-Viewer": entry.viewer_id }
              : {}),
          },
          body: JSON.stringify(payload),
          ...(signal ? { signal } : {}),
        },
      );
      if (!response.ok)
        throw new Error(`Plugin action unavailable (${response.status})`);
      return response.json() as Promise<unknown>;
    },
  };
}

export async function conversationText(context: ConversationActionContext) {
  const data = await visibleConversation(context);
  return data.messages.map((message) => message.content).join("\n\n");
}

async function visibleConversation(context: ConversationActionContext) {
  const messages =
    context.messages ??
    (
      await getAPIClient().threads.getState<AgentThreadState>(
        context.thread.thread_id,
      )
    ).values?.messages ??
    [];
  // Reuse the export's visibility and internal-marker rules for both host slots.
  return JSON.parse(formatThreadAsJSON(context.thread, messages)) as {
    messages: { id?: string; type: string; content: string }[];
  };
}

export async function latestVisibleAnswer(context: ConversationActionContext) {
  const { messages } = await visibleConversation(context);
  const answer = [...messages]
    .reverse()
    .find((message) => message.type === "ai" && !!message.id);
  return answer ? { id: answer.id!, text: answer.content } : null;
}

/** Resolve live routing metadata through the authenticated host API, including legacy bookmarks. */
export async function openConversation(
  threadId: string,
  navigate: (path: string) => void,
  signal?: AbortSignal,
) {
  signal?.throwIfAborted();
  const thread = await getAPIClient().threads.get(threadId, { signal });
  signal?.throwIfAborted();
  navigate(pathOfThread(thread));
}
