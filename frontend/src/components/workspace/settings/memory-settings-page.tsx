"use client";

import { Trash2Icon } from "lucide-react";
import { useState } from "react";
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
import {
  useClearMemory,
  useDeleteMemoryFact,
  useMemory,
} from "@/core/memory/hooks";
import type { UserMemory } from "@/core/memory/types";
import { streamdownPlugins } from "@/core/streamdown/plugins";
import { pathOfThread } from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";

import { SettingsSection } from "./settings-section";

function confidenceToLevelKey(confidence: unknown): {
  key: "veryHigh" | "high" | "normal" | "unknown";
  value?: number;
} {
  if (typeof confidence !== "number" || !Number.isFinite(confidence)) {
    return { key: "unknown" };
  }

  // Clamp to [0, 1] since confidence is expected to be a probability-like score.
  const value = Math.min(1, Math.max(0, confidence));

  // 3 levels:
  // - veryHigh: [0.85, 1]
  // - high:     [0.65, 0.85)
  // - normal:   [0, 0.65)
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

  const markdown = parts.join("\n\n");

  // Ensure every level-2 heading (##) is preceded by a horizontal rule.
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
  const clearMemory = useClearMemory();
  const deleteMemoryFact = useDeleteMemoryFact();
  const [clearDialogOpen, setClearDialogOpen] = useState(false);
  const [factToDelete, setFactToDelete] = useState<string | null>(null);

  const clearAllLabel = t.settings.memory.clearAll ?? "Clear all memory";
  const clearAllConfirmTitle =
    t.settings.memory.clearAllConfirmTitle ?? "Clear all memory?";
  const clearAllConfirmDescription =
    t.settings.memory.clearAllConfirmDescription ??
    "This will remove all saved summaries and facts. This action cannot be undone.";
  const clearAllSuccess =
    t.settings.memory.clearAllSuccess ?? "All memory cleared";
  const factDeleteConfirmTitle =
    t.settings.memory.factDeleteConfirmTitle ?? "Delete this fact?";
  const factDeleteConfirmDescription =
    t.settings.memory.factDeleteConfirmDescription ??
    "This fact will be removed from memory immediately. This action cannot be undone.";
  const factDeleteSuccess =
    t.settings.memory.factDeleteSuccess ?? "Fact deleted";
  const noFacts = t.settings.memory.noFacts ?? "No saved facts yet.";

  async function handleClearMemory() {
    try {
      await clearMemory.mutateAsync();
      toast.success(clearAllSuccess);
      setClearDialogOpen(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleDeleteFact() {
    if (!factToDelete) return;

    try {
      await deleteMemoryFact.mutateAsync(factToDelete);
      toast.success(factDeleteSuccess);
      setFactToDelete(null);
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
            <div className="flex justify-end">
              <Button
                variant="destructive"
                onClick={() => setClearDialogOpen(true)}
                disabled={clearMemory.isPending}
              >
                {clearMemory.isPending ? t.common.loading : clearAllLabel}
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

            <div className="rounded-lg border p-4">
              <div className="mb-4">
                <h3 className="text-base font-medium">
                  {t.settings.memory.markdown.facts}
                </h3>
              </div>

              {memory.facts.length === 0 ? (
                <div className="text-muted-foreground text-sm">{noFacts}</div>
              ) : (
                <div className="space-y-3">
                  {memory.facts.map((fact) => {
                    const { key } = confidenceToLevelKey(fact.confidence);
                    const confidenceText =
                      t.settings.memory.markdown.table.confidenceLevel[key];

                    return (
                      <div
                        key={fact.id}
                        className="flex flex-col gap-3 rounded-md border p-3 sm:flex-row sm:items-start sm:justify-between"
                      >
                        <div className="min-w-0 space-y-2">
                          <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
                            <span>
                              <span className="text-muted-foreground">
                                {t.settings.memory.markdown.table.category}:
                              </span>{" "}
                              {upperFirst(fact.category)}
                            </span>
                            <span>
                              <span className="text-muted-foreground">
                                {t.settings.memory.markdown.table.confidence}:
                              </span>{" "}
                              {confidenceText}
                            </span>
                            <span>
                              <span className="text-muted-foreground">
                                {t.settings.memory.markdown.table.createdAt}:
                              </span>{" "}
                              {formatTimeAgo(fact.createdAt)}
                            </span>
                          </div>
                          <p className="break-words text-sm">{fact.content}</p>
                          <a
                            href={pathOfThread(fact.source)}
                            className="text-primary text-sm underline-offset-4 hover:underline"
                          >
                            {t.settings.memory.markdown.table.view}
                          </a>
                        </div>

                        <Button
                          variant="ghost"
                          size="icon"
                          className="text-destructive hover:text-destructive shrink-0"
                          onClick={() => setFactToDelete(fact.id)}
                          disabled={deleteMemoryFact.isPending}
                          title={t.common.delete}
                        >
                          <Trash2Icon className="h-4 w-4" />
                        </Button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        )}
      </SettingsSection>

      <Dialog open={clearDialogOpen} onOpenChange={setClearDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{clearAllConfirmTitle}</DialogTitle>
            <DialogDescription>
              {clearAllConfirmDescription}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setClearDialogOpen(false)}
              disabled={clearMemory.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleClearMemory()}
              disabled={clearMemory.isPending}
            >
              {clearMemory.isPending ? t.common.loading : clearAllLabel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={factToDelete !== null}
        onOpenChange={(open) => {
          if (!open) {
            setFactToDelete(null);
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{factDeleteConfirmTitle}</DialogTitle>
            <DialogDescription>
              {factDeleteConfirmDescription}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setFactToDelete(null)}
              disabled={deleteMemoryFact.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleDeleteFact()}
              disabled={deleteMemoryFact.isPending}
            >
              {deleteMemoryFact.isPending ? t.common.loading : t.common.delete}
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
