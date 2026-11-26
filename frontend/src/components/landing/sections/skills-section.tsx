"use client";

import { DEFAULT_LOCALE, type Locale } from "@/core/i18n/locale";

import ProgressiveSkillsAnimation from "../progressive-skills-animation";
import { Section } from "../section";

type SkillsCopy = {
  eyebrow: string;
  title: string;
  subtitle: string;
};

const SKILLS_COPY: Record<Locale, SkillsCopy> = {
  "en-US": {
    eyebrow: "Progressive Context",
    title: "Agent Skills",
    subtitle:
      "DeerFlow scans lightweight skill manifests up front and loads full Markdown instructions and scripts only when a task matches — keeping context focused and fast.",
  },
  "zh-CN": {
    eyebrow: "渐进式上下文",
    title: "智能体技能（Agent Skills）",
    subtitle:
      "DeerFlow 启动时仅读取轻量级技能清单，仅在任务匹配时按需加载完整 Markdown 指令与脚本，既保持上下文精简，又支持随时扩展新能力。",
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
      index="02"
      variant="default"
      className={className}
      eyebrow={copy.eyebrow}
      title={copy.title}
      subtitle={copy.subtitle}
    >
      <ProgressiveSkillsAnimation locale={locale} />
    </Section>
  );
}
