import type { Message } from "@langchain/langgraph-sdk";

import type { Translations } from "@/core/i18n/locales/types";

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

export function pathOfThread(
  thread: ThreadRouteTarget,
  context?: Pick<AgentThreadContext, "agent_name"> | null,
) {
  const threadId = typeof thread === "string" ? thread : thread.thread_id;
  const encodedThreadId = encodeURIComponent(threadId);
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

/**
 * The thread's title, or `untitledLabel` when it has none. UI callers pass
 * the localized `t.pages.untitled`; export filenames keep the English default.
 */
export function titleOfThread(thread: AgentThread, untitledLabel = "Untitled") {
  return thread.values?.title ?? untitledLabel;
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

/**
 * English fallback names for providers without a localized
 * `threads.origin.providers.*` entry (and for callers without translations).
 */
const CHANNEL_PROVIDER_LABELS: Record<string, string> = {
  buzz: "Buzz",
  dingtalk: "DingTalk",
  discord: "Discord",
  feishu: "Feishu",
  github: "GitHub",
  qq: "QQ",
  slack: "Slack",
  telegram: "Telegram",
  wechat: "WeChat",
  wecom: "WeCom",
};

/**
 * A provider's display name: the localized `threads.origin.providers.*` entry
 * when `t` is given and knows it, else the English name, else the raw id (an
 * unknown provider only).
 */
export function labelOfChannelProvider(
  provider: string,
  t?: Pick<Translations, "threads">,
): string {
  const localized: Record<string, string> | undefined =
    t?.threads.origin.providers;
  if (localized && Object.hasOwn(localized, provider)) {
    return localized[provider]!;
  }
  return Object.hasOwn(CHANNEL_PROVIDER_LABELS, provider)
    ? CHANNEL_PROVIDER_LABELS[provider]!
    : provider;
}

export function channelSourceOfThread(
  thread: Pick<AgentThread, "metadata">,
  t?: Pick<Translations, "threads">,
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
    label: labelOfChannelProvider(normalizedProvider, t),
  };
}
