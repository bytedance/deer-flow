"use client";

import { BoxIcon } from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";
import { type SkillUsage } from "@/core/skills/usage";

import { MarkdownContent } from "../messages/markdown-content";

import { snapshotMarkdownComponents } from "./snapshot-markdown-components";
import { skillSourceLabel } from "./source-label";

export function SkillUsagePanel({ skill }: { skill: SkillUsage }) {
  const { t } = useI18n();
  // The snapshot remains intact for copying; metadata is presented separately.
  const body = skill.content.replace(
    /^\uFEFF?---\r?\n[\s\S]*?\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$)/,
    "",
  );

  return (
    <div>
      <div className="border-b px-6 py-5">
        <p
          className="text-muted-foreground mb-5 font-mono text-xs leading-relaxed break-all"
          title={skill.path}
        >
          {skill.path}
        </p>
        <div className="mb-4 flex items-center gap-3">
          <span className="bg-muted rounded-lg p-2">
            <BoxIcon className="size-5" strokeWidth={2.25} />
          </span>
          <h3 className="min-w-0 flex-1 text-lg font-semibold break-words">
            {skill.name}
          </h3>
          <span className="bg-muted text-muted-foreground shrink-0 rounded-md px-2 py-1 text-xs">
            {skillSourceLabel(skill.category, t)}
          </span>
        </div>
        <dl className="grid grid-cols-[auto_1fr] gap-x-5 gap-y-3 text-sm">
          <dt className="text-muted-foreground">{t.skillUsage.name}</dt>
          <dd className="min-w-0 break-words">{skill.name}</dd>
          <dt className="text-muted-foreground">{t.skillUsage.description}</dt>
          <dd className="min-w-0 leading-relaxed break-words">
            {skill.description || "—"}
          </dd>
        </dl>
      </div>
      {skill.partial && (
        <p
          role="status"
          className="bg-muted text-muted-foreground mx-6 mt-5 rounded-lg px-3 py-2 text-xs leading-relaxed"
        >
          {t.skillUsage.partial}
        </p>
      )}
      <div className="px-6 py-6">
        <MarkdownContent
          content={body}
          isLoading={false}
          className="text-sm"
          components={snapshotMarkdownComponents}
        />
      </div>
    </div>
  );
}
