import { GitHubLogoIcon } from "@radix-ui/react-icons";
import { ArrowRight, BookOpen, MessageSquare } from "lucide-react";
import Link from "next/link";

import {
  DEFAULT_LOCALE,
  getLangByLocale,
  type Locale,
} from "@/core/i18n/locale";

import { Section } from "../section";

type CommunitySpecRow = {
  label: string;
  value: string;
  detail: string;
};

type CommunityCopy = {
  eyebrow: string;
  title: string;
  pitch: string;
  primaryCta: string;
  discussionsCta: string;
  docsCta: string;
  workspaceCta: string;
  specs: CommunitySpecRow[];
};

const COMMUNITY_COPY: Record<Locale, CommunityCopy> = {
  "en-US": {
    eyebrow: "Open Source Community",
    title: "Build the open agent stack with us.",
    pitch:
      "Contribute skills, sandbox adapters, MCP integrations, and extensions. DeerFlow is developed in the open with builders who want transparent, self-hosted agent infrastructure.",
    primaryCta: "Join on GitHub",
    discussionsCta: "Discussions",
    docsCta: "Documentation",
    workspaceCta: "Open Workspace",
    specs: [
      {
        label: "License",
        value: "MIT Open Source",
        detail: "Self-hostable with full operator control and no lock-in.",
      },
      {
        label: "Architecture",
        value: "LangGraph + Extensible Hooks",
        detail: "Modular harness, persistent memory, and pluggable extensions.",
      },
      {
        label: "Channels",
        value: "Web · Lark · Slack · Telegram",
        detail: "One Gateway serving browser workspaces and IM workflows.",
      },
    ],
  },
  "zh-CN": {
    eyebrow: "开源社区",
    title: "共建开源智能体基础设施",
    pitch:
      "欢迎贡献技能、沙箱适配器、MCP 集成与插件扩展。DeerFlow 与全球开发者一起开放演进，打造透明、可控、可自托管的超级智能体运行时。",
    primaryCta: "在 GitHub 参与贡献",
    discussionsCta: "社区讨论",
    docsCta: "阅读文档",
    workspaceCta: "进入工作台",
    specs: [
      {
        label: "开源协议",
        value: "MIT Open Source",
        detail: "完全自托管部署，数据与运行控制权完全归属团队。",
      },
      {
        label: "核心架构",
        value: "LangGraph + Extensible Hooks",
        detail: "模块化运行时、持久化记忆体系与标准插件扩展契约。",
      },
      {
        label: "接入渠道",
        value: "Web · Lark · Slack · Telegram",
        detail: "统一 Gateway 同时支撑 Web 工作台与多端 IM 协作。",
      },
    ],
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
    <Section id="community" variant="soft" className={className}>
      <div className="grid grid-cols-1 items-center gap-8 rounded-2xl border border-[var(--df-border)] bg-[var(--df-panel)] p-7 shadow-[0_10px_30px_var(--df-shadow)] sm:p-10 lg:grid-cols-12 lg:gap-10 lg:p-12">
        {/* Left: Editorial Invitation & Actions */}
        <div className="min-w-0 lg:col-span-7">
          <p className="inline-flex flex-wrap items-center gap-2 font-mono text-xs font-medium tracking-[0.2em] text-[var(--df-accent)] uppercase">
            <span className="tabular-nums">05</span>
            <span className="text-[var(--df-border-strong)]" aria-hidden="true">
              /
            </span>
            <span>{copy.eyebrow}</span>
          </p>

          <h2 className="font-landing-serif mt-3 text-3xl leading-[1.15] font-medium tracking-[-0.02em] break-words text-[var(--df-ink)] sm:text-4xl">
            {copy.title}
          </h2>

          <p className="mt-4 max-w-xl text-sm leading-7 text-[var(--df-muted-fg)] sm:text-base">
            {copy.pitch}
          </p>

          <div className="mt-7 flex flex-wrap items-center gap-3">
            <a
              href="https://github.com/bytedance/deer-flow"
              target="_blank"
              rel="noopener noreferrer"
              className="focus-visible:ring-ring/50 inline-flex min-h-[44px] items-center justify-center gap-2 rounded-full bg-[var(--df-cta)] px-6 py-2.5 text-sm font-medium text-[var(--df-cta-fg)] transition-colors duration-150 hover:bg-[var(--df-cta-hover)] focus-visible:ring-2 focus-visible:outline-none"
            >
              <GitHubLogoIcon className="size-4 shrink-0" aria-hidden="true" />
              <span>{copy.primaryCta}</span>
            </a>

            <a
              href="https://github.com/bytedance/deer-flow/discussions"
              target="_blank"
              rel="noopener noreferrer"
              className="focus-visible:ring-ring/50 inline-flex min-h-[44px] items-center justify-center gap-2 rounded-full border border-[var(--df-border-strong)] bg-[var(--df-panel)] px-5 py-2.5 text-sm font-medium text-[var(--df-ink)] transition-colors duration-150 hover:border-[var(--df-accent)] hover:text-[var(--df-accent)] focus-visible:ring-2 focus-visible:outline-none"
            >
              <MessageSquare className="size-4 shrink-0" aria-hidden="true" />
              <span>{copy.discussionsCta}</span>
            </a>

            <Link
              href={`/${lang}/docs`}
              className="focus-visible:ring-ring/50 inline-flex min-h-[44px] items-center justify-center gap-2 rounded-full border border-[var(--df-border-strong)] bg-[var(--df-panel)] px-5 py-2.5 text-sm font-medium text-[var(--df-ink)] transition-colors duration-150 hover:border-[var(--df-accent)] hover:text-[var(--df-accent)] focus-visible:ring-2 focus-visible:outline-none"
            >
              <BookOpen className="size-4 shrink-0" aria-hidden="true" />
              <span>{copy.docsCta}</span>
            </Link>

            <Link
              href="/workspace"
              className="focus-visible:ring-ring/50 inline-flex min-h-[44px] items-center justify-center gap-2 rounded-full border border-[var(--df-border-strong)] bg-[var(--df-panel)] px-5 py-2.5 text-sm font-medium text-[var(--df-ink)] transition-colors duration-150 hover:border-[var(--df-accent)] hover:text-[var(--df-accent)] focus-visible:ring-2 focus-visible:outline-none"
            >
              <span>{copy.workspaceCta}</span>
              <ArrowRight className="size-4 shrink-0" aria-hidden="true" />
            </Link>
          </div>
        </div>

        {/* Right: Vertical Stack of 3 Editorial Spec Rows */}
        <div className="min-w-0 lg:col-span-5">
          <dl className="divide-y divide-[var(--df-border)] rounded-xl border border-[var(--df-border)] bg-[var(--df-bg-soft)] px-5 sm:px-6">
            {copy.specs.map((spec) => (
              <div key={spec.label} className="py-4 sm:py-5">
                <dt className="font-mono text-[11px] font-medium tracking-[0.16em] text-[var(--df-accent)] uppercase">
                  {spec.label}
                </dt>
                <dd className="mt-1.5 text-sm font-semibold text-[var(--df-ink)] sm:text-base">
                  {spec.value}
                </dd>
                <p className="mt-1 text-xs leading-5 text-[var(--df-muted-fg)]">
                  {spec.detail}
                </p>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </Section>
  );
}
