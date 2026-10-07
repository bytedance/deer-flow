import type { Message } from "@langchain/langgraph-sdk";

import { KB_ID_METADATA_KEY, kbIdOfThread } from "@/core/knowledge/kb-threads";

import type { AgentThread, AgentThreadContext } from "./types";

// Namespaced to match other internal metadata keys (``deerflow_sidecar``,
// ``deerflow_branch``) so it cannot collide with a future feature or a
// client-supplied key. Keep in sync with the backend thread_meta constant and
// the E2E mock-api constant.
export const THREAD_PINNED_METADATA_KEY = "deerflow_pinned";
export const THREAD_ARCHIVED_METADATA_KEY = "deerflow_archived";

export function isThreadArchived(thread: Pick<AgentThread, "metadata">) {
  return thread.metadata?.[THREAD_ARCHIVED_METADATA_KEY] === true;
}

// Reserved metadata key recording a thread's project membership
// (``metadata.deerflow_project_id``). Keep in sync with the backend
// thread_meta constant and the E2E mock-api constant.
export const THREAD_PROJECT_METADATA_KEY = "deerflow_project_id";

/**
 * Metadata persisted on thread creation (the ``onCreated`` hook in
 * `core/threads/hooks.ts`). ``agent_name`` has always been stored; ``kb_id``
 * joins it for knowledge-page conversations so the global recent-chat list
 * can exclude them, the per-kb history popover can find them, and run
 * admission can hold later turns to the same binding (spec §5.2).
 */
export function buildThreadCreatedMetadata(
  context: Readonly<Record<string, unknown>>,
): Record<string, unknown> {
  const metadata: Record<string, unknown> = {};
  if (typeof context.agent_name === "string" && context.agent_name) {
    metadata.agent_name = context.agent_name;
  }
  if (typeof context.kb_id === "string" && context.kb_id) {
    metadata[KB_ID_METADATA_KEY] = context.kb_id;
  }
  return metadata;
}

export type ChannelThreadSource = {
  type: "im_channel";
  provider: string;
  label: string;
};

type ThreadRouteTarget =
  | string
  | {
      thread_id: string;
      context?: Pick<AgentThreadContext, "agent_name"> | null;
      metadata?: Record<string, unknown> | null;
    };

/**
 * The custom agent owning a thread, from its run context first and then its
 * stored metadata; undefined for default-agent conversations.
 */
export function agentNameOfThread(thread: {
  context?: Pick<AgentThreadContext, "agent_name"> | null;
  metadata?: Record<string, unknown> | null;
}): string | undefined {
  const contextAgent = thread.context?.agent_name;
  if (contextAgent) {
    return contextAgent;
  }
  const metaAgent = thread.metadata?.agent_name;
  return typeof metaAgent === "string" && metaAgent ? metaAgent : undefined;
}

/**
 * 知识库绑定线程的规范路由。抽出来给**只有 id、没有线程对象**的调用方用
 * (知识库聊天面板就是这种:它手上是 kb id + thread id),与 `pathOfThread`
 * 的 kb 分支共用同一个构造,免得两处各写一份 URL。
 */
export function pathOfKnowledgeThread(kbId: string, threadId: string) {
  return `/workspace/knowledge?kb=${encodeURIComponent(kbId)}&thread=${encodeURIComponent(threadId)}`;
}

export function pathOfThread(
  thread: ThreadRouteTarget,
  context?: Pick<AgentThreadContext, "agent_name"> | null,
) {
  const threadId = typeof thread === "string" ? thread : thread.thread_id;
  const encodedThreadId = encodeURIComponent(threadId);
  // KB-bound threads (metadata.kb_id, spec §5.2) open inside the knowledge
  // page — the agents route would run the same rag agent WITHOUT its kb
  // binding, so retrieval could never fire there. This branch wins over the
  // agent route below because kb threads also carry metadata.agent_name.
  if (typeof thread !== "string") {
    const kbId = kbIdOfThread(thread);
    if (kbId) {
      return pathOfKnowledgeThread(kbId, threadId);
    }
  }
  const agentName =
    typeof thread === "string"
      ? context?.agent_name
      : agentNameOfThread(thread);

  return agentName
    ? `/workspace/agents/${encodeURIComponent(agentName)}/chats/${encodedThreadId}`
    : `/workspace/chats/${encodedThreadId}`;
}

export function textOfMessage(message: Message) {
  if (typeof message.content === "string") {
    return message.content;
  } else if (Array.isArray(message.content)) {
    // Flat join ("") for single-line consumers (input box, titles); the rendered
    // body uses extractContentFromMessage, which joins multi-part content with "\n".
    const text = message.content
      .map((part) =>
        typeof part === "string" ? part : part.type === "text" ? part.text : "",
      )
      .join("");
    return text.length > 0 ? text : null;
  }
  return null;
}

export function titleOfThread(thread: AgentThread) {
  return thread.values?.title ?? "Untitled";
}

export function isThreadPinned(thread: Pick<AgentThread, "metadata">) {
  return thread.metadata?.[THREAD_PINNED_METADATA_KEY] === true;
}

export function projectIdOfThread(
  thread: Pick<AgentThread, "metadata">,
): string | null {
  const projectId = thread.metadata?.[THREAD_PROJECT_METADATA_KEY];
  return typeof projectId === "string" && projectId.length > 0
    ? projectId
    : null;
}

export function sortPinnedThreads<T extends Pick<AgentThread, "metadata">>(
  threads: readonly T[],
) {
  return threads
    .map((thread, index) => ({ thread, index }))
    .sort((left, right) => {
      const pinnedDiff =
        Number(isThreadPinned(right.thread)) -
        Number(isThreadPinned(left.thread));
      return pinnedDiff || left.index - right.index;
    })
    .map(({ thread }) => thread);
}

const CHANNEL_PROVIDER_LABELS: Record<string, string> = {
  buzz: "Buzz",
  dingtalk: "DingTalk",
  discord: "Discord",
  feishu: "Feishu",
  qq: "QQ",
  slack: "Slack",
  telegram: "Telegram",
  wechat: "WeChat",
  wecom: "WeCom",
};

function labelOfChannelProvider(provider: string) {
  return CHANNEL_PROVIDER_LABELS[provider] ?? provider;
}

export function channelSourceOfThread(
  thread: Pick<AgentThread, "metadata">,
): ChannelThreadSource | null {
  const source = thread.metadata?.channel_source;
  if (!source || typeof source !== "object" || Array.isArray(source)) {
    return null;
  }

  if (Reflect.get(source, "type") !== "im_channel") {
    return null;
  }

  const provider = Reflect.get(source, "provider");
  if (typeof provider !== "string" || provider.trim().length === 0) {
    return null;
  }

  const normalizedProvider = provider.trim().toLowerCase();
  return {
    type: "im_channel",
    provider: normalizedProvider,
    label: labelOfChannelProvider(normalizedProvider),
  };
}
