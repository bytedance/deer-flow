"use client";

import { Trash2Icon } from "lucide-react";
import { useCallback, useState } from "react";
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
import { useClearMemory, useDeleteFact, useMemory } from "@/core/memory/hooks";
import type { UserMemory } from "@/core/memory/types";
import { streamdownPlugins } from "@/core/streamdown/plugins";
import { useThreads } from "@/core/threads/hooks";
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

function FactsTable({
  facts,
  t,
}: {
  facts: UserMemory["facts"];
  t: ReturnType<typeof useI18n>["t"];
}) {
  const deleteFact = useDeleteFact();
  const { data: threads } = useThreads();
  const threadTitleMap = new Map(
    (threads ?? []).map((thread) => [
      thread.thread_id,
      thread.values?.title ?? "",
    ]),
  );

  const handleDelete = useCallback(
    (factId: string) => {
      deleteFact.mutate(factId, {
        onError: () => {
          toast.error("Failed to delete fact");
        },
      });
    },
    [deleteFact],
  );

  if (facts.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">
        {t.settings.memory.markdown.empty}
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left">
            <th className="pb-2 pr-3 font-medium">
              {t.settings.memory.markdown.table.category}
            </th>
            <th className="pb-2 pr-3 font-medium">
              {t.settings.memory.markdown.table.confidence}
            </th>
            <th className="pb-2 pr-3 font-medium">
              {t.settings.memory.markdown.table.content}
            </th>
            <th className="pb-2 pr-3 font-medium">
              {t.settings.memory.markdown.table.source}
            </th>
            <th className="pb-2 pr-3 font-medium">
              {t.settings.memory.markdown.table.createdAt}
            </th>
            <th className="pb-2 font-medium" />
          </tr>
        </thead>
        <tbody>
          {facts.map((f) => {
            const { key } = confidenceToLevelKey(f.confidence);
            const levelLabel =
              t.settings.memory.markdown.table.confidenceLevel[key];
            return (
              <tr key={f.id} className="border-b last:border-0">
                <td className="py-2 pr-3">{upperFirst(f.category)}</td>
                <td className="py-2 pr-3">{levelLabel}</td>
                <td className="py-2 pr-3">{f.content}</td>
                <td className="py-2 pr-3">
                  <a
                    href={pathOfThread(f.source)}
                    className="text-primary hover:underline"
                    title={threadTitleMap.get(f.source) ?? f.source}
                  >
                    {(() => {
                      const title = threadTitleMap.get(f.source);
                      if (title && title.length > 0) {
                        return title.length > 30
                          ? `${title.slice(0, 30)}\u2026`
                          : title;
                      }
                      return f.source.slice(0, 8);
                    })()}
                  </a>
                </td>
                <td className="py-2 pr-3">{formatTimeAgo(f.createdAt)}</td>
                <td className="py-2">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="text-muted-foreground hover:text-destructive h-7 w-7"
                    onClick={() => handleDelete(f.id)}
                    disabled={deleteFact.isPending}
                  >
                    <Trash2Icon className="h-4 w-4" />
                  </Button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function MemorySettingsPage() {
  const { t } = useI18n();
  const { memory, isLoading, error } = useMemory();
  const clearMemory = useClearMemory();
  const [showClearDialog, setShowClearDialog] = useState(false);

  const handleClearAll = useCallback(() => {
    clearMemory.mutate(undefined, {
      onSuccess: () => {
        setShowClearDialog(false);
        toast.success("Memory cleared");
      },
      onError: () => {
        toast.error("Failed to clear memory");
      },
    });
  }, [clearMemory]);

  return (
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
        <>
          <div className="mb-4 flex justify-end">
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setShowClearDialog(true)}
              disabled={clearMemory.isPending}
            >
              <Trash2Icon className="mr-2 h-4 w-4" />
              Clear All Memory
            </Button>
          </div>
          <div className="rounded-lg border p-4">
            <Streamdown
              className="size-full [&>*:first-child]:mt-0 [&>*:last-child]:mb-0"
              {...streamdownPlugins}
            >
              {memoryToMarkdown(memory, t)}
            </Streamdown>

            {memory.facts.length > 0 && (
              <>
                <hr className="my-4" />
                <h2 className="mb-3 text-lg font-semibold">
                  {t.settings.memory.markdown.facts}
                </h2>
                <FactsTable facts={memory.facts} t={t} />
              </>
            )}
          </div>

          <Dialog open={showClearDialog} onOpenChange={setShowClearDialog}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Clear All Memory</DialogTitle>
                <DialogDescription>
                  This will permanently delete all memory data including user
                  context, history summaries, and facts. This action cannot be
                  undone.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button
                  variant="outline"
                  onClick={() => setShowClearDialog(false)}
                >
                  Cancel
                </Button>
                <Button
                  variant="destructive"
                  onClick={handleClearAll}
                  disabled={clearMemory.isPending}
                >
                  {clearMemory.isPending ? "Clearing..." : "Clear All"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </>
      )}
    </SettingsSection>
  );
}

function upperFirst(str: string) {
  return str.charAt(0).toUpperCase() + str.slice(1);
}
