import type { Message } from "@langchain/langgraph-sdk";

import type {
  ActiveVersionMap,
  AgentThreadState,
  AssistantVersion,
  AssistantVersionsMap,
  MessageRevision,
  MessageVersionsMap,
  VersionLogEntry,
} from "./types";

interface HumanEditInput {
  messageId: string;
  text: string;
}

interface AssistantVersionInput {
  turnId: string;
  messageId: string;
  text: string;
  contextSnapshot: AssistantVersion["contextSnapshot"];
}

interface AssistantVersionSelection {
  messageId: string;
  versionId: string;
}

function nowIsoString() {
  return new Date().toISOString();
}

function cloneMessage(message: Message): Message {
  return {
    ...message,
    additional_kwargs: message.additional_kwargs ? { ...message.additional_kwargs } : message.additional_kwargs,
    content: Array.isArray(message.content)
      ? message.content.map((part) => ({ ...part }))
      : message.content,
  } as Message;
}

function replaceMessageText(message: Message, text: string): Message {
  const next = cloneMessage(message);

  if (typeof next.content === "string") {
    next.content = text;
    return next;
  }

  if (Array.isArray(next.content)) {
    let replaced = false;
    const parts: typeof next.content = [];

    for (const part of next.content) {
      if (part.type === "text") {
        if (replaced) {
          continue;
        }
        replaced = true;
        parts.push({ ...part, text });
        continue;
      }
      parts.push({ ...part });
    }

    if (!replaced) {
      parts.unshift({ type: "text", text });
    }

    next.content = parts;
    return next;
  }

  next.content = text;
  return next;
}

function getMessageText(message: Message): string {
  if (typeof message.content === "string") {
    return message.content;
  }

  if (Array.isArray(message.content)) {
    return message.content
      .filter((part): part is Extract<(typeof message.content)[number], { type: "text" }> => part.type === "text")
      .map((part) => part.text)
      .join("\n")
      .trim();
  }

  return "";
}

function appendVersionLog(state: AgentThreadState, entry: VersionLogEntry): AgentThreadState {
  return {
    ...state,
    version_logs: [...(state.version_logs ?? []), entry],
  };
}

function seedHumanRevisions(messages: Message[], messageVersions: MessageVersionsMap, activeVersionMap: ActiveVersionMap, messageId: string): [MessageVersionsMap, ActiveVersionMap] {
  if (messageVersions[messageId]?.length) {
    return [messageVersions, activeVersionMap];
  }

  const message = messages.find((candidate) => candidate.id === messageId && candidate.type === "human");
  if (!message) {
    return [messageVersions, activeVersionMap];
  }

  const initialRevision: MessageRevision = {
    id: `${messageId}-rev-1`,
    messageId,
    text: getMessageText(message),
    createdAt: nowIsoString(),
  };

  return [
    {
      ...messageVersions,
      [messageId]: [initialRevision],
    },
    {
      ...activeVersionMap,
      [messageId]: initialRevision.id,
    },
  ];
}

function seedAssistantVersions(messages: Message[], assistantVersions: AssistantVersionsMap, activeVersionMap: ActiveVersionMap, messageId: string, turnId: string): [AssistantVersionsMap, ActiveVersionMap] {
  if (assistantVersions[messageId]?.length) {
    return [assistantVersions, activeVersionMap];
  }

  const message = messages.find((candidate) => candidate.id === messageId && candidate.type === "ai");
  if (!message) {
    return [assistantVersions, activeVersionMap];
  }

  const initialVersion: AssistantVersion = {
    id: `${messageId}-v1`,
    messageId,
    turnId,
    text: getMessageText(message),
    createdAt: nowIsoString(),
    contextSnapshot: {},
  };

  return [
    {
      ...assistantVersions,
      [messageId]: [initialVersion],
    },
    {
      ...activeVersionMap,
      [messageId]: initialVersion.id,
    },
  ];
}

function syncProjectedMessages(state: AgentThreadState): AgentThreadState {
  return {
    ...state,
    messages: projectVisibleMessages(state),
  };
}

export function projectVisibleMessages(state: AgentThreadState): Message[] {
  const activeVersionMap = state.active_version_map ?? {};
  const humanVersions = state.message_versions ?? {};
  const assistantVersions = state.assistant_versions ?? {};

  return state.messages.map((message) => {
    if (!message.id) {
      return cloneMessage(message);
    }

    if (message.type === "human") {
      const versions = humanVersions[message.id];
      const activeVersionId = activeVersionMap[message.id];
      const activeRevision = versions?.find((version) => version.id === activeVersionId) ?? versions?.at(-1);
      return activeRevision ? replaceMessageText(message, activeRevision.text) : cloneMessage(message);
    }

    if (message.type === "ai") {
      const versions = assistantVersions[message.id];
      const activeVersionId = activeVersionMap[message.id];
      const activeVersion = versions?.find((version) => version.id === activeVersionId) ?? versions?.at(-1);
      return activeVersion ? replaceMessageText(message, activeVersion.text) : cloneMessage(message);
    }

    return cloneMessage(message);
  });
}

export function buildSubmissionMessages(state: AgentThreadState): Message[] {
  return projectVisibleMessages(state);
}

export function applyHumanEdit(state: AgentThreadState, input: HumanEditInput): AgentThreadState {
  const baseMessageVersions = state.message_versions ?? {};
  const baseActiveVersionMap = state.active_version_map ?? {};
  const [seededMessageVersions, seededActiveVersionMap] = seedHumanRevisions(
    state.messages,
    baseMessageVersions,
    baseActiveVersionMap,
    input.messageId,
  );

  const existingRevisions = seededMessageVersions[input.messageId] ?? [];
  const nextRevision: MessageRevision = {
    id: `${input.messageId}-rev-${existingRevisions.length + 1}`,
    messageId: input.messageId,
    text: input.text,
    createdAt: nowIsoString(),
  };

  const nextState = syncProjectedMessages({
    ...state,
    message_versions: {
      ...seededMessageVersions,
      [input.messageId]: [...existingRevisions, nextRevision],
    },
    active_version_map: {
      ...seededActiveVersionMap,
      [input.messageId]: nextRevision.id,
    },
  });

  return appendVersionLog(nextState, {
    id: `${input.messageId}-log-${(nextState.version_logs?.length ?? 0) + 1}`,
    kind: "human_edit",
    messageId: input.messageId,
    versionId: nextRevision.id,
    createdAt: nextRevision.createdAt,
  });
}

export function appendAssistantVersion(state: AgentThreadState, input: AssistantVersionInput): AgentThreadState {
  const baseAssistantVersions = state.assistant_versions ?? {};
  const baseActiveVersionMap = state.active_version_map ?? {};
  const [seededAssistantVersions, seededActiveVersionMap] = seedAssistantVersions(
    state.messages,
    baseAssistantVersions,
    baseActiveVersionMap,
    input.messageId,
    input.turnId,
  );

  const existingVersions = seededAssistantVersions[input.messageId] ?? [];
  const nextVersion: AssistantVersion = {
    id: `${input.messageId}-v${existingVersions.length + 1}`,
    messageId: input.messageId,
    turnId: input.turnId,
    text: input.text,
    createdAt: nowIsoString(),
    contextSnapshot: input.contextSnapshot,
  };

  const nextState = syncProjectedMessages({
    ...state,
    assistant_versions: {
      ...seededAssistantVersions,
      [input.messageId]: [...existingVersions, nextVersion],
    },
    active_version_map: {
      ...seededActiveVersionMap,
      [input.messageId]: nextVersion.id,
    },
  });

  return appendVersionLog(nextState, {
    id: `${input.messageId}-log-${(nextState.version_logs?.length ?? 0) + 1}`,
    kind: "assistant_regenerate",
    messageId: input.messageId,
    versionId: nextVersion.id,
    createdAt: nextVersion.createdAt,
  });
}

export function selectAssistantVersion(state: AgentThreadState, input: AssistantVersionSelection): AgentThreadState {
  const nextState = syncProjectedMessages({
    ...state,
    active_version_map: {
      ...(state.active_version_map ?? {}),
      [input.messageId]: input.versionId,
    },
  });

  return appendVersionLog(nextState, {
    id: `${input.messageId}-log-${(nextState.version_logs?.length ?? 0) + 1}`,
    kind: "assistant_select",
    messageId: input.messageId,
    versionId: input.versionId,
    createdAt: nowIsoString(),
  });
}
