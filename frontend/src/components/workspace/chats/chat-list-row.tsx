"use client";

import { PencilIcon, PinIcon, PinOffIcon, Trash2Icon } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";

import {
  CardAction,
  ConfirmDialog,
  ItemRow,
  ItemRowMeta,
  ItemRowStatusBadge,
  ItemRowSubtitle,
  ItemRowTag,
  ItemRowTitle,
  formatWorkspaceItemTimestamp,
} from "@/components/component";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { resetThreadChatAfterDelete } from "@/components/workspace/chats/use-thread-chat";
import { ThreadChannelBadge } from "@/components/workspace/thread-channel-source";
import { useAgents, useAgentsApiEnabled } from "@/core/agents";
import { useI18n } from "@/core/i18n/hooks";
import {
  useDeleteThread,
  usePinThread,
  useRenameThread,
} from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";
import {
  channelSourceOfThread,
  isThreadPinned,
  pathOfThread,
  textOfMessage,
  titleOfThread,
} from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";
import { env } from "@/env";
import { isIMEComposing } from "@/lib/ime";

export function ChatListRow({
  thread,
  selected,
}: {
  thread: AgentThread;
  selected: boolean;
}) {
  const { t, locale } = useI18n();
  const { enabled: agentsApiEnabled } = useAgentsApiEnabled();
  const { agents } = useAgents();
  const threadHref = pathOfThread(thread);
  const channelSource = channelSourceOfThread(thread);
  const agentName = agentNameOfThread(thread);
  const agentDescription = useMemo(() => {
    if (!agentsApiEnabled || !agentName) {
      return undefined;
    }
    const agent = agents.find((entry) => entry.name === agentName);
    const description = agent?.description?.trim();
    return description && description.length > 0 ? description : undefined;
  }, [agentName, agents, agentsApiEnabled]);
  const pinned = isThreadPinned(thread);
  const preview = lastMessagePreviewOfThread(thread);
  const messageCount = messageCountOfThread(thread);
  const updatedAt = thread.updated_at;
  const updatedRelative = updatedAt ? formatTimeAgo(updatedAt, locale) : null;
  const updatedAbsolute = updatedAt
    ? formatWorkspaceItemTimestamp(updatedAt, locale)
    : null;

  const { mutate: updatePinnedThread } = usePinThread();
  const { mutate: renameThread } = useRenameThread();
  const { mutate: deleteThread, isPending: deletePending } = useDeleteThread();

  const [renameOpen, setRenameOpen] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const [deleteOpen, setDeleteOpen] = useState(false);

  const handleTogglePin = useCallback(() => {
    updatePinnedThread(
      { threadId: thread.thread_id, pinned: !pinned },
      {
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : t.chats.pinChatFailed,
          );
        },
      },
    );
  }, [pinned, t.chats.pinChatFailed, thread.thread_id, updatePinnedThread]);

  const handleDeleteConfirm = useCallback(() => {
    deleteThread(
      {
        threadId: thread.thread_id,
        onRemoteDeleted: selected
          ? () => {
              resetThreadChatAfterDelete({
                deletedThreadId: thread.thread_id,
                nextPath: "/workspace/chats",
                force: true,
              });
            }
          : undefined,
      },
      {
        onSuccess: () => setDeleteOpen(false),
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : t.chats.deleteFailed,
          );
        },
      },
    );
  }, [deleteThread, selected, t.chats.deleteFailed, thread.thread_id]);

  const submitRename = useCallback(() => {
    const next = renameValue.trim();
    if (!next) {
      return;
    }
    renameThread(
      { threadId: thread.thread_id, title: next },
      {
        onSuccess: () => {
          setRenameOpen(false);
          setRenameValue("");
        },
        onError: (error) => {
          toast.error(
            error instanceof Error && error.message
              ? error.message
              : t.common.renameFailed,
          );
        },
      },
    );
  }, [renameThread, renameValue, t.common.renameFailed, thread.thread_id]);

  const showActions = env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true";

  return (
    <>
      <ItemRow
        variant="flush"
        href={threadHref}
        selected={selected}
        className="py-2.5"
        topStart={
          <>
            <ItemRowTitle>{titleOfThread(thread)}</ItemRowTitle>
            {preview ? (
              <ItemRowSubtitle className="line-clamp-2 leading-snug">
                {preview}
              </ItemRowSubtitle>
            ) : null}
          </>
        }
        topEnd={
          updatedAbsolute || updatedRelative ? (
            <div className="text-muted-foreground flex shrink-0 items-center gap-2 text-xs whitespace-nowrap tabular-nums">
              {updatedAbsolute ? <span>{updatedAbsolute}</span> : null}
              {updatedRelative ? <span>{updatedRelative}</span> : null}
            </div>
          ) : null
        }
        bottomStart={
          <ItemRowMeta>
            {pinned ? (
              <ItemRowStatusBadge tone="info">
                {t.chats.pinnedBadge}
              </ItemRowStatusBadge>
            ) : null}
            {agentName ? (
              <ItemRowTag className="font-mono" hint={agentDescription}>
                {agentName}
              </ItemRowTag>
            ) : (
              <ItemRowTag>{t.chats.mainChat}</ItemRowTag>
            )}
            {channelSource ? (
              <ThreadChannelBadge source={channelSource} />
            ) : null}
            {messageCount != null && messageCount > 0 ? (
              <ItemRowTag>{t.chats.messageCount(messageCount)}</ItemRowTag>
            ) : null}
          </ItemRowMeta>
        }
        bottomEnd={
          showActions ? (
            <>
              <CardAction
                icon={pinned ? PinOffIcon : PinIcon}
                label={pinned ? t.chats.unpinChat : t.chats.pinChat}
                onClick={handleTogglePin}
              />
              <CardAction
                icon={PencilIcon}
                label={t.common.rename}
                onClick={() => {
                  setRenameValue(titleOfThread(thread));
                  setRenameOpen(true);
                }}
              />
              <CardAction
                icon={Trash2Icon}
                label={t.common.delete}
                variant="destructive"
                onClick={() => setDeleteOpen(true)}
              />
            </>
          ) : undefined
        }
      />

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={t.common.delete}
        description={t.chats.deleteConfirm}
        confirmLabel={t.common.delete}
        confirmVariant="destructive"
        confirmPending={deletePending}
        onConfirm={handleDeleteConfirm}
      />

      <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t.common.rename}</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <Input
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              placeholder={t.common.rename}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !isIMEComposing(e)) {
                  e.preventDefault();
                  submitRename();
                }
              }}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRenameOpen(false)}>
              {t.common.cancel}
            </Button>
            <Button onClick={submitRename}>{t.common.save}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

const LAST_MESSAGE_PREVIEW_MAX = 120;

function messageCountOfThread(
  thread: Pick<AgentThread, "values">,
): number | null {
  const messages = thread.values?.messages;
  if (!Array.isArray(messages)) {
    return null;
  }
  return messages.length;
}

function lastMessagePreviewOfThread(
  thread: Pick<AgentThread, "values">,
  maxLen = LAST_MESSAGE_PREVIEW_MAX,
): string | null {
  const messages = thread.values?.messages;
  if (!Array.isArray(messages) || messages.length === 0) {
    return null;
  }

  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const message = messages[i];
    if (!message) {
      continue;
    }
    if ("type" in message && message.type === "system") {
      continue;
    }
    const text = textOfMessage(message);
    if (!text?.trim()) {
      continue;
    }
    const normalized = text.trim().replace(/\s+/g, " ");
    if (normalized.length <= maxLen) {
      return normalized;
    }
    return `${normalized.slice(0, maxLen - 1)}…`;
  }
  return null;
}

function agentNameOfThread(
  thread: Pick<AgentThread, "context" | "metadata">,
): string | null {
  const fromContext = thread.context?.agent_name;
  if (typeof fromContext === "string" && fromContext.trim().length > 0) {
    return fromContext.trim();
  }
  const fromMetadata = thread.metadata?.agent_name;
  if (typeof fromMetadata === "string" && fromMetadata.trim().length > 0) {
    return fromMetadata.trim();
  }
  return null;
}
