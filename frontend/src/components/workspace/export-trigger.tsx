"use client";

import { Download, FileJson, FileText } from "lucide-react";
import { useCallback, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import { exportThread, type ThreadExportFormat } from "@/core/threads/export";
import { fetchThreadExportMessages } from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";

import { useThread } from "./messages/context";
import { Tooltip } from "./tooltip";

export function ExportTrigger({ threadId }: { threadId: string }) {
  const { t } = useI18n();
  const { thread, isMock } = useThread();
  const [exporting, setExporting] = useState(false);

  const messages = thread.messages;

  const handleExport = useCallback(
    async (format: ThreadExportFormat) => {
      if (messages.length === 0) {
        toast.error(t.conversation.noMessages);
        return;
      }
      setExporting(true);
      try {
        const exportMessages =
          isMock || isStaticWebsiteOnly()
            ? messages
            : await fetchThreadExportMessages(threadId);
        if (exportMessages.length === 0) {
          toast.error(t.conversation.noMessages);
          return;
        }
        const agentThread = {
          thread_id: threadId,
          updated_at: new Date().toISOString(),
          values: thread.values,
        } as AgentThread;

        exportThread(agentThread, exportMessages, format);
        toast.success(t.common.exportSuccess);
      } catch {
        toast.error(t.common.exportFailed);
      } finally {
        setExporting(false);
      }
    },
    [messages, thread.values, threadId, isMock, t],
  );

  if (messages.length === 0) {
    return null;
  }

  return (
    <DropdownMenu>
      <Tooltip content={t.common.export}>
        <DropdownMenuTrigger asChild>
          <Button
            aria-label={t.common.export}
            disabled={exporting || thread.isLoading}
            className="text-muted-foreground hover:text-foreground"
            variant="ghost"
          >
            <Download />
            <span className="hidden sm:inline">{t.common.export}</span>
          </Button>
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => handleExport("markdown")}>
          <FileText className="text-muted-foreground" />
          <span>{t.common.exportAsMarkdown}</span>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => handleExport("json")}>
          <FileJson className="text-muted-foreground" />
          <span>{t.common.exportAsJSON}</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
