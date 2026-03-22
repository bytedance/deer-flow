"use client";

import type { BaseStream, Message } from "@langchain/langgraph-sdk";
import { DownloadIcon, FileJsonIcon, FileTextIcon } from "lucide-react";
import { useCallback } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import { extractTextFromMessage } from "@/core/messages/utils";
import type { AgentThreadState } from "@/core/threads";

import { Tooltip } from "./tooltip";

function downloadFile(content: string, filename: string, mimeType: string) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function threadToMarkdown(
  title: string,
  messages: Message[],
): string {
  const lines: string[] = [];
  lines.push(`# ${title}\n`);
  lines.push(
    `Exported from DeerFlow on ${new Date().toLocaleDateString()}\n`,
  );
  lines.push("---\n");

  for (const message of messages) {
    if (message.type === "human") {
      const text = extractTextFromMessage(message);
      if (text) {
        lines.push(`## User\n`);
        lines.push(`${text}\n`);
        lines.push("---\n");
      }
    } else if (message.type === "ai") {
      const text = extractTextFromMessage(message);
      if (text) {
        lines.push(`## Assistant\n`);
        lines.push(`${text}\n`);
        lines.push("---\n");
      }
    }
  }

  return lines.join("\n");
}

function threadToJSON(
  title: string,
  messages: Message[],
): string {
  const data = {
    title,
    exportedAt: new Date().toISOString(),
    messages: messages.map((msg) => ({
      id: msg.id,
      type: msg.type,
      content: extractTextFromMessage(msg),
    })),
  };
  return JSON.stringify(data, null, 2);
}

function sanitizeFilename(title: string): string {
  return title
    .replace(/[^a-zA-Z0-9\s-]/g, "")
    .replace(/\s+/g, "-")
    .toLowerCase()
    .slice(0, 50);
}

export function ExportButton({
  thread,
}: {
  thread: BaseStream<AgentThreadState>;
}) {
  const { t } = useI18n();
  const title = thread.values?.title ?? t.pages.untitled;
  const messages = thread.messages;

  const handleExportMarkdown = useCallback(() => {
    const md = threadToMarkdown(title, messages);
    const filename = `${sanitizeFilename(title)}.md`;
    downloadFile(md, filename, "text/markdown");
  }, [title, messages]);

  const handleExportJSON = useCallback(() => {
    const json = threadToJSON(title, messages);
    const filename = `${sanitizeFilename(title)}.json`;
    downloadFile(json, filename, "application/json");
  }, [title, messages]);

  if (!messages || messages.length === 0) {
    return null;
  }

  return (
    <DropdownMenu>
      <Tooltip content={t.export.exportConversation}>
        <DropdownMenuTrigger asChild>
          <Button size="icon-sm" variant="ghost">
            <DownloadIcon size={14} />
          </Button>
        </DropdownMenuTrigger>
      </Tooltip>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={handleExportMarkdown}>
          <FileTextIcon size={14} />
          {t.export.asMarkdown}
        </DropdownMenuItem>
        <DropdownMenuItem onClick={handleExportJSON}>
          <FileJsonIcon size={14} />
          {t.export.asJSON}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
