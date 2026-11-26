import { GitHubLogoIcon } from "@radix-ui/react-icons";
import { ArrowRight, BookOpen, MessageSquare } from "lucide-react";
import Link from "next/link";

import {
  DEFAULT_LOCALE,
  getLangByLocale,
  type Locale,
} from "@/core/i18n/locale";

import { Section } from "../section";

type CommunityCopy = {
  eyebrow: string;
  title: string;
  subtitle: string;
  highlights: { value: string; label: string }[];
  primaryCta: string;
  discussionsCta: string;
  docsCta: string;
  workspaceCta: string;
};

const COMMUNITY_COPY: Record<Locale, CommunityCopy> = {
  "en-US": {
    eyebrow: "Open Source Community",
    title: "Join the Community",
    subtitle:
      "Contribute ideas, skills, extensions, and integrations to shape the future of DeerFlow. Built in the open with developers worldwide.",
    highlights: [
      { value: "MIT", label: "Permissive Open-Source License" },
      { value: "2.0", label: "Super Agent Harness Architecture" },
      { value: "100%", label: "Self-Hostable & Extensible" },
    ],
    primaryCta: "Join on GitHub",
    discussionsCta: "Discussions",
    docsCta: "Documentation",
    workspaceCta: "Open Workspace",
  },
  "zh-CN": {
    eyebrow: "开源社区",
    title: "加入 DeerFlow 社区",
    subtitle:
      "贡献你的创意、技能、扩展与集成，与全球开发者一起构建下一代开源超级智能体运行时。",
    highlights: [
      { value: "MIT", label: "宽松开源协议" },
      { value: "2.0", label: "超级智能体运行时架构" },
      { value: "100%", label: "完全自托管与可扩展" },
    ],
    primaryCta: "在 GitHub 参与贡献",
    discussionsCta: "社区讨论",
    docsCta: "阅读文档",
    workspaceCta: "进入工作台",
  },
};

export function CommunitySection({
  className,
  locale = DEFAULT_LOCALE,
}: {
  className?: string;
  locale?: Locale;
}) {
  const copy = COMMUNITY_COPY[locale] ?? COMMUNITY_COPY["en-US"];
  const lang = getLangByLocale(locale);

  return (
    <Section
      id="community"
      variant="soft"
      align="center"
      className={className}
      eyebrow={copy.eyebrow}
      title={copy.title}
      subtitle={copy.subtitle}
    >
      <div className="mx-auto max-w-3xl space-y-8">
        {/* 3-Cell Horizontal Bordered Highlights Bar */}
        <div className="grid grid-cols-1 divide-y divide-[var(--df-border,#d8d0c2)] rounded-md border border-[var(--df-border,#d8d0c2)] bg-[var(--df-panel,#fffaf1)] sm:grid-cols-3 sm:divide-x sm:divide-y-0">
          {copy.highlights.map((item) => (
            <div
              key={item.label}
              className="flex flex-col items-center justify-center px-6 py-5 text-center"
            >
              <span className="font-mono text-xl font-semibold text-[var(--df-ink,#171511)] tabular-nums">
                {item.value}
              </span>
              <span className="mt-1.5 text-xs text-[var(--df-muted-fg,#625b50)]">
                {item.label}
              </span>
            </div>
          ))}
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center justify-center gap-3">
          <a
            href="https://github.com/bytedance/deer-flow"
            target="_blank"
            rel="noopener noreferrer"
            className="focus-visible:ring-ring/50 inline-flex min-h-[44px] items-center justify-center gap-2 rounded-md bg-[var(--df-cta,#0a7c93)] px-5 py-2.5 text-sm font-medium text-[var(--df-cta-fg,#ffffff)] transition-colors duration-150 hover:bg-[var(--df-cta-hover,#086a7e)] focus-visible:ring-2 focus-visible:outline-none"
          >
            <GitHubLogoIcon className="size-4 shrink-0" aria-hidden="true" />
            <span>{copy.primaryCta}</span>
          </a>

          <a
            href="https://github.com/bytedance/deer-flow/discussions"
            target="_blank"
            rel="noopener noreferrer"
            className="focus-visible:ring-ring/50 inline-flex min-h-[44px] items-center justify-center gap-2 rounded-md border border-[var(--df-border-strong,#bdb3a2)] bg-[var(--df-panel,#fffaf1)] px-5 py-2.5 text-sm font-medium text-[var(--df-ink,#171511)] transition-colors duration-150 hover:border-[var(--df-accent,#0a7c93)] hover:text-[var(--df-accent,#0a7c93)] focus-visible:ring-2 focus-visible:outline-none"
          >
            <MessageSquare className="size-4 shrink-0" aria-hidden="true" />
            <span>{copy.discussionsCta}</span>
          </a>

          <Link
            href={`/${lang}/docs`}
            className="focus-visible:ring-ring/50 inline-flex min-h-[44px] items-center justify-center gap-2 rounded-md border border-[var(--df-border-strong,#bdb3a2)] bg-[var(--df-panel,#fffaf1)] px-5 py-2.5 text-sm font-medium text-[var(--df-ink,#171511)] transition-colors duration-150 hover:border-[var(--df-accent,#0a7c93)] hover:text-[var(--df-accent,#0a7c93)] focus-visible:ring-2 focus-visible:outline-none"
          >
            <BookOpen className="size-4 shrink-0" aria-hidden="true" />
            <span>{copy.docsCta}</span>
          </Link>

          <Link
            href="/workspace"
            className="focus-visible:ring-ring/50 inline-flex min-h-[44px] items-center justify-center gap-2 rounded-md border border-[var(--df-border-strong,#bdb3a2)] bg-[var(--df-panel,#fffaf1)] px-5 py-2.5 text-sm font-medium text-[var(--df-ink,#171511)] transition-colors duration-150 hover:border-[var(--df-accent,#0a7c93)] hover:text-[var(--df-accent,#0a7c93)] focus-visible:ring-2 focus-visible:outline-none"
          >
            <span>{copy.workspaceCta}</span>
            <ArrowRight className="size-4 shrink-0" aria-hidden="true" />
          </Link>
        </div>
      </div>
    </Section>
  );
}
