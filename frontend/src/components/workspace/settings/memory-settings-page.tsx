"use client";

import { DownloadIcon, UploadIcon } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Streamdown } from "streamdown";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useI18n } from "@/core/i18n/hooks";
import { exportMemory } from "@/core/memory/api";
import { useImportMemory, useMemory } from "@/core/memory/hooks";
import type { UserMemory } from "@/core/memory/types";
import { streamdownPlugins } from "@/core/streamdown/plugins";
import { pathOfThread } from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";

import { SettingsSection } from "./settings-section";

type PendingImport = {
  fileName: string;
  memory: UserMemory;
};

function confidenceToLevelKey(confidence: unknown): {
  key: "veryHigh" | "high" | "normal" | "unknown";
  value?: number;
} {
  if (typeof confidence !== "number" || !Number.isFinite(confidence)) {
    return { key: "unknown" };
  }

  const value = Math.min(1, Math.max(0, confidence));
  if (value >= 0.85) return { key: "veryHigh", value };
  if (value >= 0.65) return { key: "high", value };
  return { key: "normal", value };
}

function formatMemorySection(
  title: string,
  summary: string,
  updatedAt: string | undefined,
  t: ReturnType<typeof useI18n>["t"],
): string {
  const content =
    summary.trim() ||
    `<span class="text-muted-foreground">${t.settings.memory.markdown.empty}</span>`;
  return [
    `### ${title}`,
    content,
    "",
    updatedAt &&
      `> ${t.settings.memory.markdown.updatedAt}: \`${formatTimeAgo(updatedAt)}\``,
  ]
    .filter(Boolean)
    .join("\n");
}

function memoryToMarkdown(
  memory: UserMemory,
  t: ReturnType<typeof useI18n>["t"],
) {
  const parts: string[] = [];

  parts.push(`## ${t.settings.memory.markdown.overview}`);
  parts.push(
    `- **${t.common.lastUpdated}**: \`${formatTimeAgo(memory.lastUpdated)}\``,
  );

  parts.push(`\n## ${t.settings.memory.markdown.userContext}`);
  parts.push(
    formatMemorySection(
      t.settings.memory.markdown.work,
      memory.user.workContext.summary,
      memory.user.workContext.updatedAt,
      t,
    ),
  );
  parts.push(
    formatMemorySection(
      t.settings.memory.markdown.personal,
      memory.user.personalContext.summary,
      memory.user.personalContext.updatedAt,
      t,
    ),
  );
  parts.push(
    formatMemorySection(
      t.settings.memory.markdown.topOfMind,
      memory.user.topOfMind.summary,
      memory.user.topOfMind.updatedAt,
      t,
    ),
  );

  parts.push(`\n## ${t.settings.memory.markdown.historyBackground}`);
  parts.push(
    formatMemorySection(
      t.settings.memory.markdown.recentMonths,
      memory.history.recentMonths.summary,
      memory.history.recentMonths.updatedAt,
      t,
    ),
  );
  parts.push(
    formatMemorySection(
      t.settings.memory.markdown.earlierContext,
      memory.history.earlierContext.summary,
      memory.history.earlierContext.updatedAt,
      t,
    ),
  );
  parts.push(
    formatMemorySection(
      t.settings.memory.markdown.longTermBackground,
      memory.history.longTermBackground.summary,
      memory.history.longTermBackground.updatedAt,
      t,
    ),
  );

  parts.push(`\n## ${t.settings.memory.markdown.facts}`);
  if (memory.facts.length === 0) {
    parts.push(
      `<span class="text-muted-foreground">${t.settings.memory.markdown.empty}</span>`,
    );
  } else {
    parts.push(
      [
        `| ${t.settings.memory.markdown.table.category} | ${t.settings.memory.markdown.table.confidence} | ${t.settings.memory.markdown.table.content} | ${t.settings.memory.markdown.table.source} | ${t.settings.memory.markdown.table.createdAt} |`,
        "|---|---|---|---|---|",
        ...memory.facts.map((fact) => {
          const { key, value } = confidenceToLevelKey(fact.confidence);
          const levelLabel =
            t.settings.memory.markdown.table.confidenceLevel[key];
          const confidenceText =
            typeof value === "number" ? levelLabel : levelLabel;
          const sourceText =
            fact.source === "manual"
              ? t.settings.memory.manualFactSource
              : `[${t.settings.memory.markdown.table.view}](${pathOfThread(fact.source)})`;
          return `| ${upperFirst(fact.category)} | ${confidenceText} | ${fact.content} | ${sourceText} | ${formatTimeAgo(fact.createdAt)} |`;
        }),
      ].join("\n"),
    );
  }

  const markdown = parts.join("\n\n");
  const lines = markdown.split("\n");
  const out: string[] = [];
  let i = 0;
  for (const line of lines) {
    i++;
    if (i !== 1 && line.startsWith("## ")) {
      if (out.length === 0 || out[out.length - 1] !== "---") {
        out.push("---");
      }
    }
    out.push(line);
  }

  return out.join("\n");
}

export function MemorySettingsPage() {
  const { t } = useI18n();
  const { memory, isLoading, error } = useMemory();
  const importMemoryMutation = useImportMemory();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [pendingImport, setPendingImport] = useState<PendingImport | null>(null);
  const [isExporting, setIsExporting] = useState(false);

  async function handleExportMemory() {
    try {
      setIsExporting(true);
      const exportedMemory = await exportMemory();
      const fileName = `deerflow-memory-${(exportedMemory.lastUpdated || new Date().toISOString()).replace(/[:.]/g, "-")}.json`;
      const blob = new Blob([JSON.stringify(exportedMemory, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = fileName;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      toast.success(t.settings.memory.exportSuccess);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setIsExporting(false);
    }
  }

  async function handleImportFileSelection(
    event: { target: HTMLInputElement },
  ) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }

    try {
      const parsed = JSON.parse(await file.text()) as UserMemory;
      setPendingImport({
        fileName: file.name,
        memory: parsed,
      });
    } catch {
      toast.error(t.settings.memory.importInvalidFile);
    }
  }

  async function handleConfirmImport() {
    if (!pendingImport) {
      return;
    }

    try {
      await importMemoryMutation.mutateAsync(pendingImport.memory);
      toast.success(t.settings.memory.importSuccess);
      setPendingImport(null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <>
      <SettingsSection
        title={t.settings.memory.title}
        description={t.settings.memory.description}
      >
        {isLoading ? (
          <div className="text-muted-foreground text-sm">{t.common.loading}</div>
        ) : error ? (
          <div>Error: {error.message}</div>
        ) : !memory ? (
          <div className="text-muted-foreground text-sm">
            {t.settings.memory.empty}
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept=".json,application/json"
                className="hidden"
                onChange={(event) => void handleImportFileSelection(event)}
              />
              <Button
                variant="outline"
                onClick={() => fileInputRef.current?.click()}
                disabled={importMemoryMutation.isPending}
              >
                <UploadIcon className="mr-2 h-4 w-4" />
                {t.settings.memory.importButton}
              </Button>
              <Button
                variant="outline"
                onClick={() => void handleExportMemory()}
                disabled={isExporting}
              >
                <DownloadIcon className="mr-2 h-4 w-4" />
                {isExporting ? t.common.loading : t.settings.memory.exportButton}
              </Button>
            </div>

            <div className="rounded-lg border p-4">
              <Streamdown
                className="size-full [&>*:first-child]:mt-0 [&>*:last-child]:mb-0"
                {...streamdownPlugins}
              >
                {memoryToMarkdown(memory, t)}
              </Streamdown>
            </div>
          </div>
        )}
      </SettingsSection>

      <Dialog
        open={pendingImport !== null}
        onOpenChange={(open) => {
          if (!open) {
            setPendingImport(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.settings.memory.importConfirmTitle}</DialogTitle>
            <DialogDescription>
              {t.settings.memory.importConfirmDescription}
            </DialogDescription>
          </DialogHeader>
          {pendingImport ? (
            <div className="bg-muted rounded-md border p-3 text-sm">
              <div>
                <span className="text-muted-foreground">
                  {t.settings.memory.importFileLabel}:
                </span>{" "}
                {pendingImport.fileName}
              </div>
              <div>
                <span className="text-muted-foreground">
                  {t.settings.memory.markdown.facts}:
                </span>{" "}
                {pendingImport.memory.facts.length}
              </div>
              <div>
                <span className="text-muted-foreground">
                  {t.common.lastUpdated}:
                </span>{" "}
                {pendingImport.memory.lastUpdated
                  ? formatTimeAgo(pendingImport.memory.lastUpdated)
                  : "-"}
              </div>
            </div>
          ) : null}
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setPendingImport(null)}
              disabled={importMemoryMutation.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              onClick={() => void handleConfirmImport()}
              disabled={importMemoryMutation.isPending}
            >
              {importMemoryMutation.isPending ? t.common.loading : t.common.import}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function upperFirst(str: string) {
  return str.charAt(0).toUpperCase() + str.slice(1);
}
