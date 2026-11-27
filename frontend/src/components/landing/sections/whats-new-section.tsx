import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

import {
  DEFAULT_LOCALE,
  getLangByLocale,
  type Locale,
} from "@/core/i18n/locale";
import { cn } from "@/lib/utils";

import { Section } from "../section";

type FeatureHighlight = {
  badge: string;
  meta: string;
  title: string;
  description: string;
  pills?: string[];
  linkLabel: string;
  hrefPath?: string;
  externalHref?: string;
  featured?: boolean;
};

type WhatsNewCopy = {
  eyebrow: string;
  title: string;
  subtitle: string;
  features: FeatureHighlight[];
};

const WHATS_NEW_COPY: Record<Locale, WhatsNewCopy> = {
  "en-US": {
    eyebrow: "DeerFlow 2.0",
    title: "What's New in DeerFlow 2.0",
    subtitle:
      "Evolved from a Deep Research prototype into an extensible, batteries-included Super Agent harness built for real production workflows.",
    features: [
      {
        featured: true,
        badge: "Context Engineering",
        meta: "Memory & Compaction",
        title: "Long/Short-term Memory",
        description:
          "Retains user preferences, structured facts, and session goals across turns while automatically compacting long trajectories so the agent stays sharp over hours of work.",
        pills: ["Cross-thread facts", "Auto-compaction", "Structured recall"],
        linkLabel: "Memory docs",
        hrefPath: "/docs/harness/memory",
      },
      {
        featured: true,
        badge: "Long-Running Tasks",
        meta: "LangGraph Runtime",
        title: "Planning and Sub-tasking",
        description:
          "Decomposes complex goals into explicit plans and delegates scoped sub-agents sequentially or in parallel — keeping each branch isolated with bounded context.",
        pills: ["Parallel fan-out", "Scoped toolsets", "Checkpointed state"],
        linkLabel: "Sub-agents docs",
        hrefPath: "/docs/harness/subagents",
      },
      {
        badge: "Extensible",
        meta: "Skills · MCP · Plugins",
        title: "Skills and Tools",
        description:
          "Plug, play, or swap built-in tools, MCP servers, and Markdown skills without editing core harness code.",
        linkLabel: "Skills & MCP",
        hrefPath: "/docs/harness/skills",
      },
      {
        badge: "Persistent",
        meta: "Docker · K8s · Local",
        title: "Sandbox with File System",
        description:
          "Read, write, execute shell commands, and inspect artifacts in an isolated workspace — like a real computer.",
        linkLabel: "Sandbox guide",
        hrefPath: "/docs/harness/sandbox",
      },
      {
        badge: "Flexible",
        meta: "OpenAI-Compatible",
        title: "Multi-Model Support",
        description:
          "Works with Doubao, DeepSeek, OpenAI, Claude, Gemini, and any OpenAI-compatible reasoning or multimodal model.",
        linkLabel: "Configuration",
        hrefPath: "/docs/harness/configuration",
      },
      {
        badge: "MIT License",
        meta: "Self-Hosted",
        title: "Open Source",
        description:
          "Self-hosted with full operator control, transparent harness internals, and an extensible plugin contract.",
        linkLabel: "View on GitHub",
        externalHref: "https://github.com/bytedance/deer-flow",
      },
    ],
  },
  "zh-CN": {
    eyebrow: "DeerFlow 2.0",
    title: "DeerFlow 2.0 新特性",
    subtitle:
      "从深度研究框架全面演进为开箱即用、高度可扩展的超级智能体运行时（Super Agent Harness），为真实生产工作流而生。",
    features: [
      {
        featured: true,
        badge: "上下文工程",
        meta: "记忆与压缩",
        title: "长短期记忆",
        description:
          "在多轮任务中沉淀用户偏好、结构化事实与会话目标，并自动压缩超长上下文轨迹，让智能体在持久协作中始终保持专注。",
        pills: ["跨会话事实沉淀", "自动上下文压缩", "结构化召回"],
        linkLabel: "记忆文档",
        hrefPath: "/docs/harness/memory",
      },
      {
        featured: true,
        badge: "长任务执行",
        meta: "LangGraph 运行时",
        title: "规划与子任务协作",
        description:
          "先规划再执行，将复杂目标拆解为清晰步骤，并串行或并行委派子智能体独立完成，每个分支拥有独立边界与上下文。",
        pills: ["并行子任务派发", "独立工具边界", "可恢复状态图"],
        linkLabel: "子智能体文档",
        hrefPath: "/docs/harness/subagents",
      },
      {
        badge: "高度可扩展",
        meta: "Skills · MCP · 插件",
        title: "技能与工具生态",
        description:
          "自由插拔内置工具、MCP 服务与 Markdown 技能文件，无需侵入核心代码即可定制工作流。",
        linkLabel: "技能与 MCP",
        hrefPath: "/docs/harness/skills",
      },
      {
        badge: "持久化环境",
        meta: "Docker · K8s · 本地",
        title: "带文件系统的沙箱",
        description:
          "在隔离工作区中读写文件、执行命令并沉淀产物——像操作一台真正的电脑一样完成任务。",
        linkLabel: "沙箱指南",
        hrefPath: "/docs/harness/sandbox",
      },
      {
        badge: "灵活路由",
        meta: "OpenAI 兼容",
        title: "多模型支持",
        description:
          "原生支持豆包、DeepSeek、OpenAI、Claude、Gemini 及任意兼容 OpenAI 协议的推理与多模态模型。",
        linkLabel: "配置参考",
        hrefPath: "/docs/harness/configuration",
      },
      {
        badge: "MIT 协议",
        meta: "完全自托管",
        title: "开源可控",
        description:
          "完全自托管、架构透明、支持插件契约扩展，把数据与控制权交还给开发者与团队。",
        linkLabel: "访问 GitHub",
        externalHref: "https://github.com/bytedance/deer-flow",
      },
    ],
  },
};

export function WhatsNewSection({
  className,
  locale = DEFAULT_LOCALE,
}: {
  className?: string;
  locale?: Locale;
}) {
  const copy = WHATS_NEW_COPY[locale] ?? WHATS_NEW_COPY["en-US"];
  const lang = getLangByLocale(locale);

  return (
    <Section
      id="whats-new"
      index="04"
      variant="default"
      className={className}
      eyebrow={copy.eyebrow}
      title={copy.title}
      subtitle={copy.subtitle}
    >
      <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-12">
        {copy.features.map((feature, idx) => {
          const isFeatured = Boolean(feature.featured);

          return (
            <article
              key={feature.title}
              className={cn(
                "flex h-full min-w-0 flex-col border border-[var(--df-border)] transition-all duration-200",
                isFeatured
                  ? "rounded-2xl border-t-2 border-t-[var(--df-accent)] bg-[var(--df-panel)] p-6 shadow-[0_6px_22px_var(--df-shadow)] sm:p-8 lg:col-span-6"
                  : "rounded-xl bg-[var(--df-surface)] p-5 hover:border-[var(--df-accent)]/50 hover:bg-[var(--df-panel)] sm:p-6 lg:col-span-3",
              )}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span
                  className={cn(
                    "inline-flex items-center rounded-full px-2.5 py-0.5 font-mono text-[11px] font-medium",
                    isFeatured
                      ? "bg-[var(--df-accent-soft,rgba(28,93,74,0.09))] text-[var(--df-accent)]"
                      : "border border-[var(--df-border)] bg-[var(--df-panel)] text-[var(--df-text-soft)]",
                  )}
                >
                  {feature.badge}
                </span>
                <span className="font-mono text-[11px] text-[var(--df-muted-fg)] tabular-nums">
                  {String(idx + 1).padStart(2, "0")}
                </span>
              </div>

              <p className="mt-3 font-mono text-[11px] tracking-[0.06em] text-[var(--df-muted-fg)]">
                {feature.meta}
              </p>

              <h3
                className={cn(
                  "mt-2 leading-snug text-[var(--df-ink)]",
                  isFeatured
                    ? "font-landing-serif text-2xl font-medium tracking-[-0.015em] sm:text-[26px]"
                    : "text-base font-semibold sm:text-lg",
                )}
              >
                {feature.title}
              </h3>

              <p
                className={cn(
                  "mt-2.5 text-sm text-[var(--df-muted-fg)]",
                  isFeatured ? "leading-7 sm:text-[15px]" : "leading-6",
                )}
              >
                {feature.description}
              </p>

              {feature.pills && feature.pills.length > 0 && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {feature.pills.map((pill) => (
                    <span
                      key={pill}
                      className="rounded-lg border border-[var(--df-border-soft)] bg-[var(--df-surface)] px-2.5 py-1 font-mono text-[11px] text-[var(--df-text-soft)]"
                    >
                      {pill}
                    </span>
                  ))}
                </div>
              )}

              <div className="mt-auto pt-5">
                {feature.externalHref ? (
                  <a
                    href={feature.externalHref}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="focus-visible:ring-ring/50 inline-flex items-center gap-1.5 rounded font-mono text-xs font-medium text-[var(--df-accent)] transition-colors duration-150 hover:text-[var(--df-accent-strong)] focus-visible:ring-2 focus-visible:outline-none"
                  >
                    <span>{feature.linkLabel}</span>
                    <ArrowUpRight className="size-3.5" aria-hidden="true" />
                  </a>
                ) : (
                  <Link
                    href={`/${lang}${feature.hrefPath ?? "/docs"}`}
                    className="focus-visible:ring-ring/50 inline-flex items-center gap-1.5 rounded font-mono text-xs font-medium text-[var(--df-accent)] transition-colors duration-150 hover:text-[var(--df-accent-strong)] focus-visible:ring-2 focus-visible:outline-none"
                  >
                    <span>{feature.linkLabel}</span>
                    <ArrowUpRight className="size-3.5" aria-hidden="true" />
                  </Link>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </Section>
  );
}
