import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

import {
  DEFAULT_LOCALE,
  getLangByLocale,
  type Locale,
} from "@/core/i18n/locale";

import { Section } from "../section";

type FeatureHighlight = {
  badge: string;
  meta: string;
  title: string;
  description: string;
  linkLabel: string;
  hrefPath?: string;
  externalHref?: string;
};

type WhatsNewCopy = {
  eyebrow: string;
  title: string;
  subtitle: string;
  features: FeatureHighlight[];
};

const WHATS_NEW_COPY: Record<Locale, WhatsNewCopy> = {
  "en-US": {
    eyebrow: "DeerFlow 2.0 · Harness Architecture",
    title: "What's New in DeerFlow 2.0",
    subtitle:
      "DeerFlow has evolved from a Deep Research framework into an extensible, batteries-included Super Agent harness.",
    features: [
      {
        badge: "Context Engineering",
        meta: "Memory & Compaction",
        title: "Long/Short-term Memory",
        description:
          "Retains user preferences, session goals, and structured context across turns so the agent builds on past work.",
        linkLabel: "Memory docs",
        hrefPath: "/docs/harness/memory",
      },
      {
        badge: "Long-Running Tasks",
        meta: "LangGraph Runtime",
        title: "Planning and Sub-tasking",
        description:
          "Plans ahead, reasons through complexity, and delegates scoped sub-agents sequentially or in parallel.",
        linkLabel: "Sub-agents docs",
        hrefPath: "/docs/harness/subagents",
      },
      {
        badge: "Extensible",
        meta: "Skills · MCP · Plugins",
        title: "Skills and Tools",
        description:
          "Plug, play, or swap built-in tools, MCP servers, and Markdown skills to build the exact agent you need.",
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
    eyebrow: "DeerFlow 2.0 · 架构升级",
    title: "DeerFlow 2.0 新特性",
    subtitle:
      "DeerFlow 已从深度研究框架全面演进为开箱即用、高度可扩展的超级智能体运行时（Super Agent Harness）。",
    features: [
      {
        badge: "上下文工程",
        meta: "记忆与压缩",
        title: "长短期记忆",
        description:
          "沉淀用户偏好、会话目标与结构化记忆，让智能体在多轮协作中真正理解你的工作上下文。",
        linkLabel: "记忆文档",
        hrefPath: "/docs/harness/memory",
      },
      {
        badge: "长任务执行",
        meta: "LangGraph 运行时",
        title: "规划与子任务协作",
        description:
          "先规划再行动，面对复杂目标自动拆解并串行或并行委派子智能体完成执行。",
        linkLabel: "子智能体文档",
        hrefPath: "/docs/harness/subagents",
      },
      {
        badge: "高度可扩展",
        meta: "Skills · MCP · 插件",
        title: "技能与工具生态",
        description:
          "自由插拔内置工具、MCP 服务与 Markdown 技能文件，按需定制属于你的智能体。",
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
          "原生支持豆包、DeepSeek、OpenAI、Claude、Gemini 及任意兼容 OpenAI 协议的模型服务。",
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
      variant="default"
      className={className}
      eyebrow={copy.eyebrow}
      title={copy.title}
      subtitle={copy.subtitle}
    >
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
        {copy.features.map((feature) => (
          <article
            key={feature.title}
            className="flex h-full min-w-0 flex-col rounded-md border border-[var(--df-border,#d8d0c2)] bg-[var(--df-panel,#fffaf1)] p-6 transition-colors duration-150 hover:border-[var(--df-accent,#0a7c93)]/60 sm:p-7"
          >
            <div className="flex flex-wrap items-center gap-2.5">
              <span className="inline-flex items-center rounded border border-[var(--df-border,#d8d0c2)] bg-[var(--df-surface,#fbf6ec)] px-2.5 py-0.5 font-mono text-xs font-medium text-[var(--df-ink,#171511)]">
                {feature.badge}
              </span>
              <span className="font-mono text-xs text-[var(--df-muted-fg,#625b50)]">
                {feature.meta}
              </span>
            </div>

            <h3 className="mt-4 text-lg leading-snug font-semibold text-[var(--df-ink,#171511)] sm:text-xl">
              {feature.title}
            </h3>

            <p className="mt-2.5 text-sm leading-6 text-[var(--df-muted-fg,#625b50)]">
              {feature.description}
            </p>

            <div className="mt-auto pt-5">
              {feature.externalHref ? (
                <a
                  href={feature.externalHref}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="focus-visible:ring-ring/50 inline-flex items-center gap-1.5 rounded font-mono text-xs font-medium text-[var(--df-ink,#171511)] transition-colors duration-150 hover:text-[var(--df-accent,#0a7c93)] focus-visible:ring-2 focus-visible:outline-none"
                >
                  <span>{feature.linkLabel}</span>
                  <ArrowUpRight className="size-3.5" aria-hidden="true" />
                </a>
              ) : (
                <Link
                  href={`/${lang}${feature.hrefPath ?? "/docs"}`}
                  className="focus-visible:ring-ring/50 inline-flex items-center gap-1.5 rounded font-mono text-xs font-medium text-[var(--df-ink,#171511)] transition-colors duration-150 hover:text-[var(--df-accent,#0a7c93)] focus-visible:ring-2 focus-visible:outline-none"
                >
                  <span>{feature.linkLabel}</span>
                  <ArrowUpRight className="size-3.5" aria-hidden="true" />
                </Link>
              )}
            </div>
          </article>
        ))}
      </div>
    </Section>
  );
}
