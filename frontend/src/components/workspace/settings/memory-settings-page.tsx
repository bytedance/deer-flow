"use client";

import { Streamdown } from "streamdown";

import { useI18n } from "@/core/i18n/hooks";
import { useMemory } from "@/core/memory/hooks";
import type { UserMemory } from "@/core/memory/types";
import { streamdownPluginsSafe } from "@/core/streamdown/plugins";
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

function escapeMarkdownText(value: string): string {
  return value
    .replace(/\\/g, "\\\\")
    .replace(/\|/g, "\\|")
    .replace(/\[/g, "\\[")
    .replace(/\]/g, "\\]")
    .replace(/\(/g, "\\(")
    .replace(/\)/g, "\\)")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function escapeTableCell(value: string): string {
  return escapeMarkdownText(value).replace(/\r?\n/g, " ").trim();
}

function formatMemorySection(
  title: string,
  summary: string,
  updatedAt: string | undefined,
  t: ReturnType<typeof useI18n>["t"],
): string {
  const content =
    (summary.trim() ? escapeMarkdownText(summary.trim()) : "") ||
    `_${escapeMarkdownText(t.settings.memory.markdown.empty)}_`;
  return [
    `### ${escapeMarkdownText(title)}`,
    content,
    "",
    updatedAt &&
      `> ${escapeMarkdownText(t.settings.memory.markdown.updatedAt)}: \`${formatTimeAgo(updatedAt)}\``,
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
    `- **${escapeMarkdownText(t.common.lastUpdated)}**: \`${formatTimeAgo(memory.lastUpdated)}\``,
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
    parts.push(`_${escapeMarkdownText(t.settings.memory.markdown.empty)}_`);
  } else {
    parts.push(
      [
        `| ${escapeMarkdownText(t.settings.memory.markdown.table.category)} | ${escapeMarkdownText(t.settings.memory.markdown.table.confidence)} | ${escapeMarkdownText(t.settings.memory.markdown.table.content)} | ${escapeMarkdownText(t.settings.memory.markdown.table.source)} | ${escapeMarkdownText(t.settings.memory.markdown.table.createdAt)} |`,
        "|---|---|---|---|---|",
        ...memory.facts.map((f) => {
          const { key, value } = confidenceToLevelKey(f.confidence);
          const levelLabel =
            t.settings.memory.markdown.table.confidenceLevel[key];
          const confidenceText =
            typeof value === "number" ? `${levelLabel}` : levelLabel;
          const sourceLink =
            f.source && f.source !== "unknown"
              ? `[${escapeMarkdownText(t.settings.memory.markdown.table.view)}](${pathOfThread(encodeURIComponent(f.source))})`
              : "-";
          return `| ${escapeTableCell(upperFirst(f.category))} | ${escapeTableCell(confidenceText)} | ${escapeTableCell(f.content)} | ${sourceLink} | ${escapeTableCell(formatTimeAgo(f.createdAt))} |`;
        }),
      ].join("\n"),
    );
  }

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
        <div className="rounded-lg border p-4">
          <Streamdown
            className="size-full [&>*:first-child]:mt-0 [&>*:last-child]:mb-0"
            {...streamdownPluginsSafe}
          >
            {memoryToMarkdown(memory, t)}
          </Streamdown>
        </div>
      )}
    </SettingsSection>
  );
}

function upperFirst(str: string) {
  return str.charAt(0).toUpperCase() + str.slice(1);
}
