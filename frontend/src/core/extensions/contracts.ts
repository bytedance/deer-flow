import type { Message } from "@langchain/langgraph-sdk";

import type { Translations } from "@/core/i18n";
import type { AgentThread } from "@/core/threads/types";

import type { ExtensionDocumentation } from "./documentation";

export type ExtensionSettings = Readonly<
  Record<string, boolean | number | string>
>;
export type SurfaceSlot = "page";
export type ExtensionRequestOptions = Pick<
  RequestInit,
  "method" | "headers" | "body" | "signal"
>;
export type SurfaceContext = {
  namespace: string;
  locale: string;
  settings: ExtensionSettings;
  threadId?: string;
  signal: AbortSignal;
  callBackend: FrontendServices["callBackend"];
  /** Authenticated HTTP to contributed /api/extensions/ routes. Routes own authorization. */
  requestBackend?: (
    path: string,
    options?: ExtensionRequestOptions,
  ) => Promise<Response>;
  /** Host resolves current thread ownership before navigating; unavailable on older hosts. */
  openConversation?: (threadId: string) => Promise<void>;
};
export type PluginSurface = {
  id: string;
  slot: SurfaceSlot;
  title: string;
  /** Optional sidebar entry for a page surface; the host owns its URL. */
  navigation?: { label: string; labelZh?: string; icon?: string };
  /** Mount synchronously; async work must observe context.signal. */
  mount: (
    root: HTMLElement,
    context: SurfaceContext,
  ) => { dispose: () => void };
};
export type FrontendContribution = {
  viewer_id?: string | null;
  namespace: string;
  module: string | null;
  entry: string | null;
  /** Known transports: inline-v1 and assets-v1; unknown values fail per plugin. */
  transport?: string | null;
  title: string;
  description: string;
  settings: ExtensionSettings;
  backend_actions?: string[];
  model_tools?: string[];
  documentation?: ExtensionDocumentation;
  runtime_only?: boolean;
};
export type ConversationActionContext = {
  thread: AgentThread;
  messages?: Message[];
};
export type FrontendServices = {
  callBackend: (
    action: string,
    payload: Record<string, unknown>,
  ) => Promise<unknown>;
  conversationText: (context: ConversationActionContext) => Promise<string>;
  latestVisibleAnswer?: (
    context: ConversationActionContext,
  ) => Promise<{ id: string; text: string } | null>;
  showMessage: (message: string) => void;
};
export type ConversationAction = {
  id: string;
  label: string;
  icon: string;
  available: (settings: ExtensionSettings) => boolean;
  execute: (
    context: ConversationActionContext,
    services: FrontendServices,
  ) => Promise<void>;
};
export type ConversationActionGroup = {
  label: string;
  icon: string;
  actions: ConversationAction[];
};

export type ExtensionMention = {
  namespace: string;
  provider: string;
  id: string;
  label: string;
};
export type MentionContext = Pick<
  SurfaceContext,
  "namespace" | "locale" | "settings" | "threadId" | "signal" | "callBackend"
>;
export type MentionProvider = {
  id: string;
  label: string;
  search: (
    query: string,
    context: MentionContext,
  ) => Promise<readonly { id: string; label: string; description?: string }[]>;
};

/** Optional file renderer. The host owns the URL, authorization and byte limit. */
export type ArtifactPreviewContext = {
  filename: string;
  locale: string;
  signal: AbortSignal;
  readFile: () => Promise<ArrayBuffer>;
  onError: () => void;
  /** Available after readFile; scoped to viewer, file bytes and renderer. In-memory only. */
  getReadingState?: () => unknown;
  saveReadingState?: (state: unknown) => void;
};
export type ArtifactPreviewRenderer = {
  id: string;
  /** Lowercase extensions without a dot; exact matches only. */
  extensions: string[];
  mount: (
    root: HTMLElement,
    context: ArtifactPreviewContext,
  ) => { dispose: () => void };
};

/** Browser package API v1. Modules are installed by trusted deployment operators. */
export interface FrontendExtension {
  apiVersion: 1;
  module: string;
  icon?: string;
  surfaces?: PluginSurface[];
  mentionProviders?: MentionProvider[];
  artifactPreviews?: ArtifactPreviewRenderer[];
  conversationActions?: (
    t: Translations,
    locale?: string,
  ) => ConversationActionGroup;
}
