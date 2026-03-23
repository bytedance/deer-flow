import type { BaseStream } from "@langchain/langgraph-sdk/react";
import { Undo2Icon } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
  Conversation,
  ConversationContent,
} from "@/components/ai-elements/conversation";
import { usePromptInputController } from "@/components/ai-elements/prompt-input";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tooltip } from "@/components/workspace/tooltip";
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

export function MessageList({
  className,
  threadId,
  thread,
  onRewindSuccess,
  paddingBottom = 160,
}: {
  className?: string;
  threadId: string;
  thread: BaseStream<AgentThreadState>;
  onRewindSuccess?: () => void | Promise<void>;
  paddingBottom?: number;
}) {
  const { t } = useI18n();
  const rehypePlugins = useRehypeSplitWordsIntoSpans(thread.isLoading);
  const updateSubtask = useUpdateSubtask();
  const promptInputController = usePromptInputController();
  const [rewindingAnchorId, setRewindingAnchorId] = useState<string | null>(
    null,
  );
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmAnchorId, setConfirmAnchorId] = useState<string | null>(null);
  const [optimisticRewindAnchorId, setOptimisticRewindAnchorId] = useState<
    string | null
  >(null);
  const [optimisticMessages, setOptimisticMessages] =
    useState<typeof thread.messages | null>(null);
  const rewindRequestIdRef = useRef(0);
  const messages = optimisticMessages ?? thread.messages;

  useEffect(() => {
    if (!optimisticRewindAnchorId) {
      return;
    }
    const stillHasAnchor = thread.messages.some(
      (m) => m.id === optimisticRewindAnchorId,
    );
    if (!stillHasAnchor) {
      setOptimisticRewindAnchorId(null);
      setOptimisticMessages(null);
    }
  }, [optimisticRewindAnchorId, thread.messages]);
  const openConfirm = useCallback((anchorUserMessageId: string) => {
    if (thread.isLoading || rewindingAnchorId) {
      return;
    }
    setConfirmAnchorId(anchorUserMessageId);
    setConfirmOpen(true);
  }, [rewindingAnchorId, thread.isLoading]);

  const confirmMessagePreview = (() => {
    if (!confirmAnchorId) {
      return "";
    }
    const msg = thread.messages.find(
      (m) => m.type === "human" && m.id === confirmAnchorId,
    );
    if (!msg) {
      return "";
    }
    return extractTextFromMessage(msg);
  })();

  const handleRewind = useCallback(
    async (anchorUserMessageId: string) => {
      if (thread.isLoading || rewindingAnchorId) {
        return;
      }
      const requestId = ++rewindRequestIdRef.current;
      const anchorIndex = thread.messages.findIndex(
        (m) => m.type === "human" && m.id === anchorUserMessageId,
      );
      if (anchorIndex >= 0) {
        setOptimisticRewindAnchorId(anchorUserMessageId);
        setOptimisticMessages(thread.messages.slice(0, anchorIndex));
      }
      setRewindingAnchorId(anchorUserMessageId);
      try {
        const response = await fetch(
          `${getBackendBaseURL()}/api/threads/${threadId}/rewind`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              anchor_user_message_id: anchorUserMessageId,
            }),
          },
        );
        if (!response.ok) {
          throw new Error(`rewind failed: ${response.status}`);
        }
        const data = (await response.json()) as {
          filled_text?: string;
        };
        if (requestId !== rewindRequestIdRef.current) {
          return;
        }
        if (onRewindSuccess) {
          await onRewindSuccess();
        }
        const filledText =
          typeof data.filled_text === "string" ? data.filled_text : "";
        promptInputController.textInput.setInput(filledText);
        setTimeout(() => {
          const textarea = document.querySelector("textarea");
          if (textarea) {
            textarea.focus();
            textarea.selectionStart = textarea.value.length;
            textarea.selectionEnd = textarea.value.length;
          }
        }, 100);
        setConfirmOpen(false);
        setConfirmAnchorId(null);
        toast.custom(
          () => (
            <div className="w-full text-center">已回到本轮对话发起前</div>
          ),
          {
            className:
              "w-fit max-w-[calc(100vw-2rem)] rounded-md border bg-popover px-4 py-2.5 text-sm text-popover-foreground shadow-md",
            closeButton: false,
          },
        );
      } catch (err) {
        console.error(err);
        setOptimisticRewindAnchorId(null);
        setOptimisticMessages(null);
        toast.custom(
          () => (
            <div className="w-full text-center text-destructive">回撤失败</div>
          ),
          {
            className: "w-fit max-w-[calc(100vw-2rem)]",
            closeButton: false,
          },
        );
      } finally {
        if (requestId === rewindRequestIdRef.current) {
          setRewindingAnchorId(null);
        }
      }
    },
    [
      onRewindSuccess,
      promptInputController.textInput,
      rewindingAnchorId,
      thread.isLoading,
      threadId,
    ],
  );

  if (thread.isThreadLoading && messages.length === 0) {
    return <MessageListSkeleton />;
  }

  let hasSeenHuman = false;

  return (
    <>
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确定要回到本轮对话发起前吗？</DialogTitle>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setConfirmOpen(false);
                setConfirmAnchorId(null);
              }}
            >
              {t.common.cancel}
            </Button>
            <Button
              onClick={() => {
                if (confirmAnchorId) {
                  void handleRewind(confirmAnchorId);
                }
              }}
              disabled={!confirmAnchorId || thread.isLoading || !!rewindingAnchorId}
            >
              确定
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Conversation
      className={cn("flex size-full flex-col justify-center", className)}
    >
      <ConversationContent className="mx-auto w-full max-w-(--container-width-md) gap-8 pt-12">
        {groupMessages(messages, (group) => {
          if (group.type === "human" || group.type === "assistant") {
            if (group.type === "human") {
              const anchorId =
                typeof group.messages[0]?.id === "string"
                  ? group.messages[0].id
                  : null;
              const canRewind = hasSeenHuman;
              hasSeenHuman = true;
              return (
                <div key={group.id} className="group/turn flex flex-col gap-2">
                  {group.messages.map((msg) => {
                    return (
                      <MessageListItem
                        key={`${group.id}/${msg.id}`}
                        message={msg}
                        isLoading={thread.isLoading}
                      />
                    );
                  })}
                  {anchorId && canRewind && (
                    <div className="relative z-30 flex justify-end">
                      <Tooltip content="回到本轮对话发起前">
                        <Button
                          size="icon-sm"
                          variant="ghost"
                          disabled={
                            thread.isLoading || rewindingAnchorId === anchorId
                          }
                          onClick={() => openConfirm(anchorId)}
                          className="pointer-events-auto opacity-60 group-hover/turn:opacity-100"
                        >
                          <Undo2Icon className="h-4 w-4" />
                        </Button>
                      </Tooltip>
                    </div>
                  )}
                </div>
              );
            }
            return group.messages.map((msg) => {
              return (
                <MessageListItem
                  key={`${group.id}/${msg.id}`}
                  message={msg}
                  isLoading={thread.isLoading}
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
                  className="text-muted-foreground font-norma pt-2 text-sm"
                >
                  {t.subtasks.executing(tasks.size)}
                </div>,
              );
              const taskIds = message.tool_calls?.map(
                (toolCall) => toolCall.id,
              );
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
    </>
  );
}
