"use client";

import { DEFAULT_LOCALE, type Locale } from "@/core/i18n/locale";

import ProgressiveSkillsAnimation from "../progressive-skills-animation";
import { Section } from "../section";

type SkillsCopy = {
  eyebrow: string;
  title: string;
  subtitle: string;
  highlights: { label: string; detail: string }[];
};

const SKILLS_COPY: Record<Locale, SkillsCopy> = {
  "en-US": {
    eyebrow: "Extensible Workflows",
    title: "Agent Skills",
    subtitle:
      "Agent Skills are loaded progressively — only what's needed, when it's needed. Extend DeerFlow with your own Markdown skill files, or use our built-in library.",
    highlights: [
      {
        label: "On-demand context",
        detail: "Read SKILL.md and topic templates only when a task matches.",
      },
      {
        label: "Plain Markdown + scripts",
        detail:
          "Author portable workflows without modifying core harness code.",
      },
      {
        label: "Built-in & custom library",
        detail: "Ships with research, slides, web, and data analysis skills.",
      },
    ],
  },
  "zh-CN": {
    eyebrow: "可扩展工作流",
    title: "智能体技能（Agent Skills）",
    subtitle:
      "技能按需渐进加载——只在需要时读取必要上下文。你可以用 Markdown 编写自定义技能，也可以直接使用内置技能库。",
    highlights: [
      {
        label: "按需加载上下文",
        detail: "仅在任务匹配时读取 SKILL.md 与细分领域模板，节省 Token。",
      },
      {
        label: "Markdown 与脚本",
        detail: "无需改动核心代码即可扩展可复用的任务工作流。",
      },
      {
        label: "内置与自定义技能库",
        detail: "开箱即用覆盖深度研究、演示文稿、网页构建与数据分析。",
      },
    ],
  },
};

export function SkillsSection({
  className,
  locale = DEFAULT_LOCALE,
}: {
  className?: string;
  locale?: Locale;
}) {
  const copy = SKILLS_COPY[locale] ?? SKILLS_COPY["en-US"];

  return (
    <Section
      id="skills"
      variant="default"
      className={className}
      eyebrow={copy.eyebrow}
      title={copy.title}
      subtitle={copy.subtitle}
    >
      <div className="space-y-6">
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {copy.highlights.map((item) => (
            <div
              key={item.label}
              className="rounded-md border border-[var(--df-border,#d8d0c2)] bg-[var(--df-panel,#fffaf1)] p-4 sm:p-5"
            >
              <p className="font-mono text-xs font-semibold text-[var(--df-accent,#0a7c93)]">
                {item.label}
              </p>
              <p className="mt-1.5 text-sm leading-6 text-[var(--df-muted-fg,#625b50)]">
                {item.detail}
              </p>
            </div>
          ))}
        </div>

        <ProgressiveSkillsAnimation locale={locale} />
      </div>
    </Section>
  );
}
