import type { Translations } from "@/core/i18n/locales/types";

import type { AgentThread } from "./types";
import { channelSourceOfThread, labelOfChannelProvider } from "./utils";

/**
 * Server-owned run/thread origin key (`metadata.deerflow_origin`), stamped by
 * the Gateway on runs a server-side launcher starts and on the thread it
 * creates for them. Pinned by `contracts/thread_origin_contract.json`. Not to
 * be confused with the message-level `deerflow_scheduled_origin` key
 * (`core/messages/utils.ts`), which marks the scheduled prompt inside a run.
 */
export const DEERFLOW_ORIGIN_KEY = "deerflow_origin";

export const THREAD_ORIGIN_KINDS = [
  "extension",
  "github",
  "im_channel",
  "mcp_notification",
  "schedule",
] as const;

export type ThreadOriginKind = (typeof THREAD_ORIGIN_KINDS)[number];

export type ThreadOrigin =
  | { kind: "schedule" }
  | { kind: "im_channel"; provider: string }
  | { kind: "github"; provider: "github" }
  | { kind: "extension"; namespace: string | null }
  | { kind: "mcp_notification" };

export function isThreadOriginKind(value: unknown): value is ThreadOriginKind {
  return (
    typeof value === "string" &&
    (THREAD_ORIGIN_KINDS as readonly string[]).includes(value)
  );
}

function nonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0
    ? value.trim()
    : null;
}

function originFromMetadata(value: unknown): ThreadOrigin | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const kind: unknown = Reflect.get(value, "kind");
  if (!isThreadOriginKind(kind)) {
    return null;
  }
  switch (kind) {
    case "schedule":
    case "mcp_notification":
      return { kind };
    case "github":
      return { kind, provider: "github" };
    case "extension":
      return {
        kind,
        namespace: nonEmptyString(Reflect.get(value, "namespace")),
      };
    case "im_channel": {
      const provider = nonEmptyString(Reflect.get(value, "provider"));
      return provider ? { kind, provider: provider.toLowerCase() } : null;
    }
  }
}

/**
 * Who created a thread, for the sidebar marker. In order:
 * 1. the server-owned `metadata.deerflow_origin`;
 * 2. else the IM `channel_source` marker (also covers IM threads from before
 *    the origin key existed; a `github` provider is a GitHub agent thread);
 * 3. else a legacy scheduled run thread (`metadata.scheduled_task_id`);
 * 4. else `null`: the user's own chat.
 */
export function threadOriginOf(
  thread: Pick<AgentThread, "metadata">,
): ThreadOrigin | null {
  const metadata = thread.metadata;
  const stamped = originFromMetadata(metadata?.[DEERFLOW_ORIGIN_KEY]);
  if (stamped) {
    // An IM origin without a provider falls through to `channel_source`.
    return stamped;
  }
  const channel = channelSourceOfThread(thread);
  if (channel) {
    return channel.provider === "github"
      ? { kind: "github", provider: "github" }
      : { kind: "im_channel", provider: channel.provider };
  }
  if (typeof metadata?.scheduled_task_id === "string") {
    return { kind: "schedule" };
  }
  return null;
}

/**
 * The marker label of an origin ("Scheduled run", "From Feishu", "From
 * GitHub", "From an extension"); `null` when the origin has no marker
 * (`mcp_notification` runs never create threads).
 */
export function labelOfThreadOrigin(
  origin: ThreadOrigin | null,
  t: Pick<Translations, "threads">,
): string | null {
  if (!origin) {
    return null;
  }
  const labels = t.threads.origin;
  switch (origin.kind) {
    case "schedule":
      return labels.schedule;
    case "github":
      return labels.github;
    case "extension":
      return labels.extension;
    case "im_channel":
      return labels.fromProvider(labelOfChannelProvider(origin.provider, t));
    case "mcp_notification":
      return null;
  }
}
