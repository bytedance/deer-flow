import type { BaseStream } from "@langchain/langgraph-sdk/react";
import { useEffect, useMemo, useState } from "react";

import {
  Conversation,
  ConversationContent,
} from "@/components/ai-elements/conversation";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import {
  extractContentFromMessage,
  extractPresentFilesFromMessage,
  extractTextFromMessage,
  groupMessages,
  hasContent,
  hasPresentFiles,
  hasReasoning,
  isConversationSummaryMessage,
  isHiddenFromUIMessage,
} from "@/core/messages/utils";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import type { Subtask } from "@/core/tasks";
import { useUpdateSubtask } from "@/core/tasks/context";
import type { AgentThreadState } from "@/core/threads";
import { cn } from "@/lib/utils";

import { ArtifactFileList } from "../artifacts/artifact-file-list";
import { StreamingIndicator } from "../streaming-indicator";

import { MarkdownContent } from "./markdown-content";
import { MessageGroup } from "./message-group";
import { MessageListItem } from "./message-list-item";
import { MessageListSkeleton } from "./skeleton";
import { SubtaskCard } from "./subtask-card";

export const MESSAGE_LIST_DEFAULT_PADDING_BOTTOM = 160;
export const MESSAGE_LIST_FOLLOWUPS_EXTRA_PADDING_BOTTOM = 80;

type ThreadHistoryEntry = {
  checkpoint_id: string;
  values?: {
    messages?: AgentThreadState["messages"];
  };
};

const HISTORY_PAGE_SIZE = 25;
const HISTORY_PAGE_LIMIT = 4;

function messageIdentity(message: AgentThreadState["messages"][number]) {
  if (message.id) {
    return message.id;
  }
  const content =
    typeof message.content === "string"
      ? message.content
      : JSON.stringify(message.content);
  return `${message.type}:${message.name ?? ""}:${content}`;
}

function buildDisplayMessages(
  latestMessages: AgentThreadState["messages"],
  historyEntries: ThreadHistoryEntry[],
) {
  const latestVisibleIds = new Set(
    latestMessages
      .filter(
        (message) =>
          !isHiddenFromUIMessage(message) && !isConversationSummaryMessage(message),
      )
      .map(messageIdentity),
  );

  const mergedMessages: AgentThreadState["messages"] = [];
  const seenMessages = new Set<string>();
  const oldestFirstEntries = [...historyEntries].reverse();

  for (const entry of oldestFirstEntries) {
    for (const message of entry.values?.messages ?? []) {
      const identity = messageIdentity(message);
      if (seenMessages.has(identity)) {
        continue;
      }
      seenMessages.add(identity);
      mergedMessages.push(message);
    }
  }

  const restoredMessages = mergedMessages.filter(
    (message) => !isConversationSummaryMessage(message),
  );
  const hasRecoveredHistory = restoredMessages.some(
    (message) => !latestVisibleIds.has(messageIdentity(message)),
  );

  if (!hasRecoveredHistory) {
    return latestMessages;
  }

  return restoredMessages;
}

export function MessageList({
  className,
  threadId,
  thread,
  paddingBottom = MESSAGE_LIST_DEFAULT_PADDING_BOTTOM,
}: {
  className?: string;
  threadId: string;
  thread: BaseStream<AgentThreadState>;
  paddingBottom?: number;
}) {
  const { t } = useI18n();
  const rehypePlugins = useRehypeSplitWordsIntoSpans(thread.isLoading);
  const updateSubtask = useUpdateSubtask();
  const [historyEntries, setHistoryEntries] = useState<ThreadHistoryEntry[]>([]);
  const [historyLoadedForThread, setHistoryLoadedForThread] = useState<
    string | null
  >(null);
  const messages = useMemo(() => {
    if (historyLoadedForThread !== threadId || historyEntries.length === 0) {
      return thread.messages;
    }
    return buildDisplayMessages(thread.messages, historyEntries);
  }, [historyEntries, historyLoadedForThread, thread.messages, threadId]);
  const hasSummaryMessage = useMemo(
    () => thread.messages.some(isConversationSummaryMessage),
    [thread.messages],
  );

  useEffect(() => {
    setHistoryEntries([]);
    setHistoryLoadedForThread(null);
  }, [threadId]);

  useEffect(() => {
    if (!threadId || !hasSummaryMessage || thread.isThreadLoading) {
      return;
    }
    if (historyLoadedForThread === threadId) {
      return;
    }

    const controller = new AbortController();

    const loadThreadHistory = async () => {
      const entries: ThreadHistoryEntry[] = [];
      let before: string | null = null;

      for (let page = 0; page < HISTORY_PAGE_LIMIT; page += 1) {
        const response = await fetch(
          `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/history`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              limit: HISTORY_PAGE_SIZE,
              before,
            }),
            signal: controller.signal,
          },
        );

        if (!response.ok) {
          throw new Error(`Failed to load thread history: ${response.status}`);
        }

        const pageEntries = (await response.json()) as ThreadHistoryEntry[];
        const rootEntries = pageEntries.filter(
          (entry) => (entry.values?.messages?.length ?? 0) > 0,
        );
        entries.push(...rootEntries);

        if (pageEntries.length < HISTORY_PAGE_SIZE) {
          break;
        }

        before = pageEntries.at(-1)?.checkpoint_id ?? null;
        if (!before) {
          break;
        }
      }

      setHistoryEntries(entries);
      setHistoryLoadedForThread(threadId);
    };

    void loadThreadHistory().catch((error: unknown) => {
      if (controller.signal.aborted) {
        return;
      }
      console.error("Failed to restore summarized thread history", error);
      setHistoryEntries([]);
      setHistoryLoadedForThread(threadId);
    });

    return () => controller.abort();
  }, [hasSummaryMessage, historyLoadedForThread, thread.isThreadLoading, threadId]);

  if (thread.isThreadLoading && messages.length === 0) {
    return <MessageListSkeleton />;
  }
  return (
    <Conversation
      className={cn("flex size-full flex-col justify-center", className)}
    >
      <ConversationContent className="mx-auto w-full max-w-(--container-width-md) gap-8 pt-12">
        {groupMessages(messages, (group) => {
          if (group.type === "human" || group.type === "assistant") {
            return group.messages.map((msg) => {
              return (
                <MessageListItem
                  key={`${group.id}/${msg.id}`}
                  message={msg}
                  isLoading={thread.isLoading}
                  threadId={threadId}
                />
              );
            });
          } else if (group.type === "assistant:clarification") {
            const message = group.messages[0];
            if (message && hasContent(message)) {
              return (
                <MarkdownContent
                  key={group.id}
                  content={extractContentFromMessage(message)}
                  isLoading={thread.isLoading}
                  rehypePlugins={rehypePlugins}
                />
              );
            }
            return null;
          } else if (group.type === "assistant:present-files") {
            const files: string[] = [];
            for (const message of group.messages) {
              if (hasPresentFiles(message)) {
                const presentFiles = extractPresentFilesFromMessage(message);
                files.push(...presentFiles);
              }
            }
            return (
              <div className="w-full" key={group.id}>
                {group.messages[0] && hasContent(group.messages[0]) && (
                  <MarkdownContent
                    content={extractContentFromMessage(group.messages[0])}
                    isLoading={thread.isLoading}
                    rehypePlugins={rehypePlugins}
                    className="mb-4"
                  />
                )}
                <ArtifactFileList files={files} threadId={threadId} />
              </div>
            );
          } else if (group.type === "assistant:subagent") {
            const tasks = new Set<Subtask>();
            for (const message of group.messages) {
              if (message.type === "ai") {
                for (const toolCall of message.tool_calls ?? []) {
                  if (toolCall.name === "task") {
                    const task: Subtask = {
                      id: toolCall.id!,
                      subagent_type: toolCall.args.subagent_type,
                      description: toolCall.args.description,
                      prompt: toolCall.args.prompt,
                      status: "in_progress",
                    };
                    updateSubtask(task);
                    tasks.add(task);
                  }
                }
              } else if (message.type === "tool") {
                const taskId = message.tool_call_id;
                if (taskId) {
                  const result = extractTextFromMessage(message);
                  if (result.startsWith("Task Succeeded. Result:")) {
                    updateSubtask({
                      id: taskId,
                      status: "completed",
                      result: result
                        .split("Task Succeeded. Result:")[1]
                        ?.trim(),
                    });
                  } else if (result.startsWith("Task failed.")) {
                    updateSubtask({
                      id: taskId,
                      status: "failed",
                      error: result.split("Task failed.")[1]?.trim(),
                    });
                  } else if (result.startsWith("Task timed out")) {
                    updateSubtask({
                      id: taskId,
                      status: "failed",
                      error: result,
                    });
                  } else {
                    updateSubtask({
                      id: taskId,
                      status: "in_progress",
                    });
                  }
                }
              }
            }
            const results: React.ReactNode[] = [];
            for (const message of group.messages.filter(
              (message) => message.type === "ai",
            )) {
              if (hasReasoning(message)) {
                results.push(
                  <MessageGroup
                    key={"thinking-group-" + message.id}
                    messages={[message]}
                    isLoading={thread.isLoading}
                  />,
                );
              }
              results.push(
                <div
                  key="subtask-count"
                  className="text-muted-foreground pt-2 text-sm font-normal"
                >
                  {t.subtasks.executing(tasks.size)}
                </div>,
              );
              const taskIds = message.tool_calls
                ?.filter((toolCall) => toolCall.name === "task")
                .map((toolCall) => toolCall.id);
              for (const taskId of taskIds ?? []) {
                results.push(
                  <SubtaskCard
                    key={"task-group-" + taskId}
                    taskId={taskId!}
                    isLoading={thread.isLoading}
                  />,
                );
              }
            }
            return (
              <div
                key={"subtask-group-" + group.id}
                className="relative z-1 flex flex-col gap-2"
              >
                {results}
              </div>
            );
          }
          return (
            <MessageGroup
              key={"group-" + group.id}
              messages={group.messages}
              isLoading={thread.isLoading}
            />
          );
        })}
        {thread.isLoading && <StreamingIndicator className="my-4" />}
        <div style={{ height: `${paddingBottom}px` }} />
      </ConversationContent>
    </Conversation>
  );
}
