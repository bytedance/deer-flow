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
  hasToolCalls,
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
import { MessageTokenUsageList } from "./message-token-usage";
import { MessageListSkeleton } from "./skeleton";
import { SubtaskCard } from "./subtask-card";

export const MESSAGE_LIST_DEFAULT_PADDING_BOTTOM = 160;
export const MESSAGE_LIST_FOLLOWUPS_EXTRA_PADDING_BOTTOM = 80;

type ThreadMessagesResponse = {
  messages?: AgentThreadState["messages"];
};

function messageFingerprint(message: AgentThreadState["messages"][number]) {
  const content =
    typeof message.content === "string"
      ? message.content
      : JSON.stringify(message.content);
  const toolCallId =
    "tool_call_id" in message && typeof message.tool_call_id === "string"
      ? message.tool_call_id
      : "";
  return `${message.type}:${message.name ?? ""}:${toolCallId}:${content}`;
}

function mergeTranscriptWithLiveMessages(
  transcriptMessages: AgentThreadState["messages"],
  liveMessages: AgentThreadState["messages"],
) {
  if (transcriptMessages.length === 0) {
    return liveMessages;
  }

  const merged = [...transcriptMessages];
  const seenIds = new Set(
    transcriptMessages
      .map((message) => message.id)
      .filter((id): id is string => typeof id === "string" && id.length > 0),
  );
  const seenFingerprints = new Set(transcriptMessages.map(messageFingerprint));

  for (const message of liveMessages) {
    if (isHiddenFromUIMessage(message)) {
      continue;
    }
    if (message.id && seenIds.has(message.id)) {
      continue;
    }
    const fingerprint = messageFingerprint(message);
    if (seenFingerprints.has(fingerprint)) {
      continue;
    }
    if (message.id) {
      seenIds.add(message.id);
    }
    seenFingerprints.add(fingerprint);
    merged.push(message);
  }

  return merged;
}

export function MessageList({
  className,
  threadId,
  thread,
  paddingBottom = MESSAGE_LIST_DEFAULT_PADDING_BOTTOM,
  tokenUsageEnabled = false,
}: {
  className?: string;
  threadId: string;
  thread: BaseStream<AgentThreadState>;
  paddingBottom?: number;
  tokenUsageEnabled?: boolean;
}) {
  const { t } = useI18n();
  const rehypePlugins = useRehypeSplitWordsIntoSpans(thread.isLoading);
  const updateSubtask = useUpdateSubtask();
  const [transcriptMessages, setTranscriptMessages] = useState<
    AgentThreadState["messages"]
  >([]);
  const [transcriptLoadedForThread, setTranscriptLoadedForThread] = useState<
    string | null
  >(null);
  const messages = useMemo(() => {
    if (transcriptLoadedForThread !== threadId) {
      return thread.messages;
    }
    return mergeTranscriptWithLiveMessages(transcriptMessages, thread.messages);
  }, [
    thread.messages,
    threadId,
    transcriptLoadedForThread,
    transcriptMessages,
  ]);

  useEffect(() => {
    setTranscriptMessages([]);
    setTranscriptLoadedForThread(null);
  }, [threadId]);

  useEffect(() => {
    if (!threadId || thread.isThreadLoading || thread.isLoading) {
      return;
    }

    const controller = new AbortController();

    const loadTranscript = async () => {
      const response = await fetch(
        `${getBackendBaseURL()}/api/threads/${encodeURIComponent(threadId)}/messages`,
        {
          signal: controller.signal,
        },
      );

      if (!response.ok) {
        throw new Error(`Failed to load thread messages: ${response.status}`);
      }

      const payload = (await response.json()) as ThreadMessagesResponse;
      setTranscriptMessages(payload.messages ?? []);
      setTranscriptLoadedForThread(threadId);
    };

    void loadTranscript().catch((error: unknown) => {
      if (controller.signal.aborted) {
        return;
      }
      console.error("Failed to load canonical thread transcript", error);
      setTranscriptMessages([]);
      setTranscriptLoadedForThread(threadId);
    });

    return () => controller.abort();
  }, [thread.isLoading, thread.isThreadLoading, threadId]);

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
                  tokenUsageEnabled={tokenUsageEnabled}
                />
              );
            });
          } else if (group.type === "assistant:clarification") {
            const message = group.messages[0];
            if (message && hasContent(message)) {
              return (
                <div key={group.id} className="w-full">
                  <MarkdownContent
                    content={extractContentFromMessage(message)}
                    isLoading={thread.isLoading}
                    rehypePlugins={rehypePlugins}
                  />
                  <MessageTokenUsageList
                    enabled={tokenUsageEnabled}
                    isLoading={thread.isLoading}
                    messages={group.messages}
                  />
                </div>
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
                <MessageTokenUsageList
                  enabled={tokenUsageEnabled}
                  isLoading={thread.isLoading}
                  messages={group.messages}
                />
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
                <MessageTokenUsageList
                  enabled={tokenUsageEnabled}
                  isLoading={thread.isLoading}
                  messages={group.messages}
                />
              </div>
            );
          }
          const tokenUsageMessages = group.messages.filter(
            (message) =>
              message.type === "ai" &&
              (hasToolCalls(message) ? true : !hasContent(message)),
          );
          return (
            <div key={"group-" + group.id} className="w-full">
              <MessageGroup
                messages={group.messages}
                isLoading={thread.isLoading}
              />
              <MessageTokenUsageList
                enabled={tokenUsageEnabled}
                isLoading={thread.isLoading}
                messages={tokenUsageMessages}
              />
            </div>
          );
        })}
        {thread.isLoading && <StreamingIndicator className="my-4" />}
        <div style={{ height: `${paddingBottom}px` }} />
      </ConversationContent>
    </Conversation>
  );
}
