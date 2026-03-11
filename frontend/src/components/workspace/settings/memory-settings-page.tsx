"use client";

import { Trash2 } from "lucide-react";
import { Streamdown } from "streamdown";

import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import {
  useDeleteMemoryFact,
  useMemory,
  useMemoryConfig,
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

function FactsList({ memory }: { memory: UserMemory }) {
  const { t } = useI18n();
  const { mutate: deleteFact, deletingFactId } = useDeleteMemoryFact();

  if (memory.facts.length === 0) {
    return (
      <p className="text-muted-foreground text-sm">
        {t.settings.memory.markdown.empty}
      </p>
    );
  }

  return (
    <ul className="divide-y">
      {memory.facts.map((f) => {
        const { key } = confidenceToLevelKey(f.confidence);
        const levelLabel =
          t.settings.memory.markdown.table.confidenceLevel[key];
        return (
          <li key={f.id} className="flex items-start gap-3 py-2">
            <div className="min-w-0 flex-1 space-y-0.5">
              <p className="text-sm">{f.content}</p>
              <p className="text-muted-foreground text-xs">
                {upperFirst(f.category)} · {levelLabel} ·{" "}
                <a
                  href={pathOfThread(f.source)}
                  className="hover:underline"
                  target="_blank"
                  rel="noreferrer"
                >
                  {t.settings.memory.markdown.table.view}
                </a>{" "}
                · {formatTimeAgo(f.createdAt)}
              </p>
            </div>
            <button
              aria-label={t.settings.memory.deleteFact}
              title={t.settings.memory.deleteFact}
              disabled={deletingFactId === f.id}
              onClick={() => deleteFact(f.id)}
              className="text-muted-foreground hover:text-destructive mt-0.5 shrink-0 transition-colors disabled:opacity-50"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export function MemorySettingsPage() {
  const { t } = useI18n();
  const { memory, isLoading, error } = useMemory();
  const { config, updateConfig, isUpdating } = useMemoryConfig();

  return (
    <SettingsSection
      title={t.settings.memory.title}
      description={t.settings.memory.description}
    >
      {/* injection_enabled toggle */}
      <div className="flex items-center justify-between gap-4 rounded-lg border p-4">
        <div className="space-y-0.5">
          <p className="text-sm font-medium">
            {t.settings.memory.injectionEnabled}
          </p>
          <p className="text-muted-foreground text-xs">
            {t.settings.memory.injectionEnabledDescription}
          </p>
        </div>
        <Switch
          checked={config?.injection_enabled ?? true}
          disabled={isUpdating}
          onCheckedChange={(checked) =>
            updateConfig({ injection_enabled: checked })
          }
        />
      </div>

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
          {/* Summary sections (user/history) - unchanged Markdown rendering */}
          <div className="rounded-lg border p-4">
            <Streamdown
              className="size-full [&>*:first-child]:mt-0 [&>*:last-child]:mb-0"
              {...streamdownPlugins}
            >
              {memoryToMarkdown(memory, t)}
            </Streamdown>
          </div>

          {/* Facts section - interactive list with delete buttons */}
          <div className="rounded-lg border p-4">
            <h3 className="mb-3 text-sm font-semibold">
              {t.settings.memory.markdown.facts}
            </h3>
            <FactsList memory={memory} />
          </div>
        </>
      )}
    </SettingsSection>
  );
}

function upperFirst(str: string) {
  return str.charAt(0).toUpperCase() + str.slice(1);
}
