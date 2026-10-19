"use client";

import { BoxIcon } from "lucide-react";
import dynamic from "next/dynamic";

import { useI18n } from "@/core/i18n/hooks";
import { type SkillUsage } from "@/core/skills/usage";

import { useMaybeMessageDetails } from "../message-details/context";
import { MessageDetailsMenu } from "../message-details/message-details-menu";

import { SkillUsageCopyAction } from "./skill-usage-copy-action";
import { skillSourceLabel } from "./source-label";

const SkillUsagePanel = dynamic(() =>
  import("./skill-usage-panel").then((module) => module.SkillUsagePanel),
);

export function SkillUsageMenu({ skills }: { skills: SkillUsage[] }) {
  const { t } = useI18n();
  const details = useMaybeMessageDetails();
  if (!details || skills.length === 0) return null;

  return (
    <MessageDetailsMenu
      label={t.skillUsage.used}
      title={t.skillUsage.title}
      icon={<BoxIcon className="size-4" strokeWidth={2.5} />}
      entries={skills.map((skill) => ({
        id: `${skill.path}:${skill.content_hash}`,
        title: skill.name,
        subtitle: skillSourceLabel(skill.category, t),
        onSelect: (origin) =>
          details.select(
            {
              id: `skill:${skill.path}:${skill.content_hash}`,
              title: "SKILL.md",
              content: <SkillUsagePanel skill={skill} />,
              actions: <SkillUsageCopyAction content={skill.content} />,
            },
            origin,
          ),
      }))}
    />
  );
}
