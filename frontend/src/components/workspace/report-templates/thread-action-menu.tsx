"use client";

import {
  Download,
  FileJson,
  FileText,
  MoreHorizontal,
  Pencil,
  Share2,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { SidebarMenuAction } from "@/components/ui/sidebar";
import { getAPIClient } from "@/core/api";
import { useI18n } from "@/core/i18n/hooks";
import {
  exportThreadAsJSON,
  exportThreadAsMarkdown,
} from "@/core/threads/export";
import { useDeleteThread, useRenameThread } from "@/core/threads/hooks";
import type { AgentThread, AgentThreadState } from "@/core/threads/types";
import { pathOfThread, titleOfThread } from "@/core/threads/utils";
import { isIMEComposing } from "@/lib/ime";

interface ThreadActionMenuProps {
  thread: AgentThread;
  /** Render trigger as a SidebarMenuAction (small icon, show on hover). Default true. */
  sidebarStyle?: boolean;
  /** Called after a rename completes. */
  onRename?: (threadId: string, newTitle: string) => void;
  /**
   * Custom Tailwind group name for hover visibility (e.g. "report-thread").
   * Required when items are nested inside another group/menu-item to avoid
   * hover bubbling making all items' action buttons visible at once.
   */
  groupName?: string;
}

export function ThreadActionMenu({
  thread,
  sidebarStyle = true,
  onRename,
  groupName,
}: ThreadActionMenuProps) {
  const { t } = useI18n();
  const router = useRouter();
  const pathname = usePathname();
  const { thread_id: threadIdFromPath } = useParams<{ thread_id: string }>();

  const { mutate: deleteThread } = useDeleteThread();
  const { mutate: renameThread } = useRenameThread();

  const [renameDialogOpen, setRenameDialogOpen] = useState(false);
  const [renameValue, setRenameValue] = useState("");

  const handleRenameClick = useCallback(() => {
    setRenameValue(titleOfThread(thread));
    setRenameDialogOpen(true);
  }, [thread]);

  const handleRenameSubmit = useCallback(() => {
    if (renameValue.trim()) {
      renameThread(
        { threadId: thread.thread_id, title: renameValue.trim() },
        {
          onSuccess: () => {
            onRename?.(thread.thread_id, renameValue.trim());
          },
        },
      );
      setRenameDialogOpen(false);
      setRenameValue("");
    }
  }, [renameThread, thread.thread_id, renameValue, onRename]);

  const handleDelete = useCallback(() => {
    deleteThread({ threadId: thread.thread_id });
    if (thread.thread_id === threadIdFromPath) {
      void router.push(pathOfThread("new"));
    }
  }, [deleteThread, thread.thread_id, threadIdFromPath, router]);

  const handleShare = useCallback(async () => {
    const PRODUCTION_URL = "https://inscphm.com";
    const isLocalhost =
      window.location.hostname === "localhost" ||
      window.location.hostname === "127.0.0.1";
    const baseUrl = isLocalhost ? PRODUCTION_URL : window.location.origin;
    const shareUrl = `${baseUrl}${pathOfThread(thread)}`;
    try {
      await navigator.clipboard.writeText(shareUrl);
      toast.success(t.clipboard.linkCopied);
    } catch {
      toast.error(t.clipboard.failedToCopyToClipboard);
    }
  }, [thread, t]);

  const handleExport = useCallback(
    async (format: "markdown" | "json") => {
      try {
        const apiClient = getAPIClient();
        const state = await apiClient.threads.getState<AgentThreadState>(
          thread.thread_id,
        );
        const messages = state.values?.messages ?? [];
        if (messages.length === 0) {
          toast.error(t.conversation.noMessages);
          return;
        }
        if (format === "markdown") {
          exportThreadAsMarkdown(thread, messages);
        } else {
          exportThreadAsJSON(thread, messages);
        }
        toast.success(t.common.exportSuccess);
      } catch {
        toast.error("Failed to export conversation");
      }
    },
    [thread, t],
  );

  const hoverGroup = groupName ? `group-hover/${groupName}:opacity-100 group-focus-within/${groupName}:opacity-100` : "";

  const triggerButton = sidebarStyle ? (
    <DropdownMenuTrigger asChild>
      <SidebarMenuAction
        showOnHover={!groupName}
        className={
          groupName
            ? `bg-background/50 hover:bg-background md:opacity-0 ${hoverGroup} data-[state=open]:opacity-100`
            : "bg-background/50 hover:bg-background"
        }
      >
        <MoreHorizontal />
        <span className="sr-only">{t.common.more}</span>
      </SidebarMenuAction>
    </DropdownMenuTrigger>
  ) : (
    <DropdownMenuTrigger asChild>
      <Button variant="ghost" size="icon" className="size-7">
        <MoreHorizontal className="size-4" />
        <span className="sr-only">{t.common.more}</span>
      </Button>
    </DropdownMenuTrigger>
  );

  return (
    <>
      <DropdownMenu>
        {triggerButton}
        <DropdownMenuContent
          className="w-48 rounded-lg"
          side="right"
          align="start"
        >
          <DropdownMenuItem onSelect={handleRenameClick}>
            <Pencil className="text-muted-foreground" />
            <span>{t.common.rename}</span>
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={handleShare}>
            <Share2 className="text-muted-foreground" />
            <span>{t.common.share}</span>
          </DropdownMenuItem>
          <DropdownMenuSub>
            <DropdownMenuSubTrigger>
              <Download className="text-muted-foreground" />
              <span>{t.common.export}</span>
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
              <DropdownMenuItem onSelect={() => handleExport("markdown")}>
                <FileText className="text-muted-foreground" />
                <span>{t.common.exportAsMarkdown}</span>
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => handleExport("json")}>
                <FileJson className="text-muted-foreground" />
                <span>{t.common.exportAsJSON}</span>
              </DropdownMenuItem>
            </DropdownMenuSubContent>
          </DropdownMenuSub>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={handleDelete}>
            <Trash2 className="text-muted-foreground" />
            <span>{t.common.delete}</span>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={renameDialogOpen} onOpenChange={setRenameDialogOpen}>
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
                  handleRenameSubmit();
                }
              }}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setRenameDialogOpen(false)}
            >
              {t.common.cancel}
            </Button>
            <Button onClick={handleRenameSubmit}>{t.common.save}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
