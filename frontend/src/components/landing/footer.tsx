"use client";

import { GitHubLogoIcon } from "@radix-ui/react-icons";
import { ArrowUpRight, BookOpen, Check, Copy, Terminal } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  type LandingDocsLang,
  type LandingLocale,
  useOptionalLandingLocale,
} from "@/core/i18n/landing";
import { cn } from "@/lib/utils";

export type FooterProps = {
  className?: string;
  locale?: LandingLocale;
};

type FooterLink = {
  label: string;
  href: string;
  external?: boolean;
};

type FooterColumn = {
  heading: string;
  links: FooterLink[];
};

const QUICK_START_COMMANDS =
  "git clone https://github.com/bytedance/deer-flow.git && cd deer-flow && make dev";

function DeerFlowFooterMark() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className="size-6 shrink-0 text-[var(--df-ink)]"
    >
      <path
        d="M4.5 18.5C7.2 16.5 9.6 16.5 12 18C14.4 19.5 16.8 19.5 19.5 17.5"
        stroke="var(--df-accent)"
        strokeWidth="1.75"
        strokeLinecap="round"
      />
      <path
        d="M12 15.25V10.5M12 10.5L7.5 6.5M12 10.5L16.5 6.5M9.5 8.25L8 4.5M14.5 8.25L16 4.5"
        stroke="currentColor"
        strokeWidth="1.65"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="5.25" r="1.35" fill="var(--df-accent)" />
    </svg>
  );
}

function getFooterCopy(locale: LandingLocale, docsLang: LandingDocsLang) {
  const isZh = locale === "zh-CN";

  const columns: FooterColumn[] = [
    {
      heading: isZh ? "产品" : "Product",
      links: [
        { label: isZh ? "架构总览" : "Architecture", href: "/#architecture" },
        { label: isZh ? "精选案例" : "Case Studies", href: "/#case-studies" },
        { label: isZh ? "技能系统" : "Skills", href: "/#skills" },
        { label: isZh ? "隔离沙箱" : "Sandbox", href: "/#sandbox" },
        { label: isZh ? "最新特性" : "What's New", href: "/#whats-new" },
      ],
    },
    {
      heading: isZh ? "核心能力" : "Capabilities",
      links: [
        {
          label: isZh ? "模型与服务商" : "Models & Providers",
          href: `/${docsLang}/docs/reference/model-providers`,
        },
        {
          label: isZh ? "MCP 工具" : "MCP Tools",
          href: `/${docsLang}/docs/harness/mcp`,
        },
        {
          label: isZh ? "技能生态" : "Skills Ecosystem",
          href: `/${docsLang}/docs/harness/skills`,
        },
        {
          label: isZh ? "扩展与插件" : "Extensions",
          href: `/${docsLang}/docs/harness/extensions`,
        },
        {
          label: isZh ? "IM 渠道" : "IM Channels",
          href: `/${docsLang}/docs/application/configuration`,
        },
      ],
    },
    {
      heading: isZh ? "开发者" : "Developers",
      links: [
        {
          label: isZh ? "快速开始" : "Quick Start",
          href: `/${docsLang}/docs/application/quick-start`,
        },
        {
          label: isZh ? "完整文档" : "Documentation",
          href: `/${docsLang}/docs`,
        },
        {
          label: isZh ? "Harness 指南" : "Harness Guide",
          href: `/${docsLang}/docs/harness/quick-start`,
        },
        {
          label: isZh ? "部署指南" : "Deployment",
          href: `/${docsLang}/docs/application/deployment-guide`,
        },
        { label: isZh ? "技术博客" : "Blog", href: "/blog/posts" },
      ],
    },
    {
      heading: isZh ? "开源社区" : "Community",
      links: [
        {
          label: "GitHub",
          href: "https://github.com/bytedance/deer-flow",
          external: true,
        },
        {
          label: isZh ? "社区讨论" : "Discussions",
          href: "https://github.com/bytedance/deer-flow/discussions",
          external: true,
        },
        {
          label: isZh ? "问题反馈" : "Issues",
          href: "https://github.com/bytedance/deer-flow/issues",
          external: true,
        },
        {
          label: isZh ? "参与贡献" : "Contributing",
          href: "https://github.com/bytedance/deer-flow/blob/main/CONTRIBUTING.md",
          external: true,
        },
        {
          label: isZh ? "进入工作区" : "Open Workspace",
          href: "/workspace/chats/new",
        },
      ],
    },
  ];

  return {
    mission: isZh
      ? "面向长周期任务的开源超级智能体 Harness——将隔离沙箱、长期记忆、渐进式技能与子智能体编排融为一体。"
      : "An open-source super agent harness for long-horizon work — uniting isolated sandboxes, persistent memory, progressive skills, and subagent orchestration.",
    quickStartEyebrow: isZh ? "本地快速运行" : "RUN LOCALLY",
    docsLinkLabel: isZh ? "阅读文档" : "Docs",
    githubLinkLabel: "GitHub",
    copyCommandAria: isZh ? "复制启动命令" : "Copy quick-start commands",
    copiedLabel: isZh ? "已复制" : "Copied",
    license: isZh ? "MIT 开源许可证" : "MIT License",
    attribution: isZh
      ? "由 ByteDance 开源并持续维护"
      : "Open-sourced by ByteDance",
    columns,
  };
}

export function Footer({ className, locale }: FooterProps) {
  const { locale: activeLocale, docsLang } = useOptionalLandingLocale(locale);
  const year = useMemo(() => new Date().getFullYear(), []);
  const copy = getFooterCopy(activeLocale, docsLang);
  const [copied, setCopied] = useState(false);
  const resetTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (resetTimerRef.current !== null) {
        window.clearTimeout(resetTimerRef.current);
      }
    };
  }, []);

  const handleCopyCommand = () => {
    if (typeof navigator === "undefined" || !navigator.clipboard?.writeText) {
      return;
    }
    void navigator.clipboard
      .writeText(QUICK_START_COMMANDS)
      .then(() => {
        setCopied(true);
        if (resetTimerRef.current !== null) {
          window.clearTimeout(resetTimerRef.current);
        }
        resetTimerRef.current = window.setTimeout(() => {
          setCopied(false);
        }, 1800);
      })
      .catch(() => {
        // Ignore clipboard permission errors in restricted contexts.
      });
  };

  return (
    <footer
      className={cn(
        "border-t border-[var(--df-border)] bg-[var(--df-bg-soft)] pt-14 pb-10 text-[var(--df-ink)] sm:pt-16",
        className,
      )}
    >
      <div className="mx-auto max-w-[1280px] px-4 sm:px-8 lg:px-12">
        {/* Tier 1: Brand mission + inline quick-start card */}
        <div className="grid grid-cols-1 gap-8 border-b border-[var(--df-border)] pb-12 lg:grid-cols-12 lg:items-center lg:gap-10">
          <div className="flex flex-col gap-4 lg:col-span-6">
            <Link
              href="/"
              className="focus-visible:ring-ring/50 inline-flex w-fit items-center gap-2.5 rounded-sm transition-opacity hover:opacity-80 focus-visible:ring-2 focus-visible:outline-none"
            >
              <DeerFlowFooterMark />
              <span className="font-landing-serif text-2xl font-medium tracking-[-0.02em] text-[var(--df-ink)]">
                DeerFlow
              </span>
            </Link>
            <p className="max-w-md text-sm leading-6 text-[var(--df-muted-fg)] sm:text-[15px]">
              {copy.mission}
            </p>
          </div>

          <div className="lg:col-span-6">
            <div className="rounded-xl border border-[var(--df-border)] bg-[var(--df-panel)] p-5 shadow-[0_2px_12px_var(--df-shadow)]">
              <div className="mb-3 flex items-center justify-between gap-2">
                <span className="inline-flex items-center gap-1.5 font-mono text-[11px] font-medium tracking-[0.14em] text-[var(--df-accent)] uppercase">
                  <Terminal className="size-3.5" aria-hidden="true" />
                  <span>{copy.quickStartEyebrow}</span>
                </span>
                <button
                  type="button"
                  onClick={handleCopyCommand}
                  aria-label={copy.copyCommandAria}
                  className="focus-visible:ring-ring/50 inline-flex h-7 items-center gap-1 rounded-md border border-[var(--df-border-soft)] bg-[var(--df-surface)] px-2 font-mono text-[11px] text-[var(--df-muted-fg)] transition-colors duration-150 hover:border-[var(--df-border-strong)] hover:text-[var(--df-ink)] focus-visible:ring-2 focus-visible:outline-none"
                >
                  {copied ? (
                    <>
                      <Check
                        className="size-3 text-[var(--df-accent)]"
                        aria-hidden="true"
                      />
                      <span>{copy.copiedLabel}</span>
                    </>
                  ) : (
                    <Copy className="size-3" aria-hidden="true" />
                  )}
                </button>
              </div>

              <pre className="overflow-x-auto rounded-lg border border-[var(--df-border-soft)] bg-[var(--df-surface)] px-3.5 py-2.5 font-mono text-xs leading-5 text-[var(--df-ink)]">
                <code>
                  <span className="text-[var(--df-muted-fg)] select-none">
                    ${" "}
                  </span>
                  git clone https://github.com/bytedance/deer-flow.git
                  {"\n"}
                  <span className="text-[var(--df-muted-fg)] select-none">
                    ${" "}
                  </span>
                  cd deer-flow &amp;&amp; make dev
                </code>
              </pre>

              <div className="mt-3.5 flex flex-wrap items-center gap-2">
                <Link
                  href={`/${docsLang}/docs`}
                  className="focus-visible:ring-ring/50 inline-flex h-8 items-center gap-1.5 rounded-full border border-[var(--df-border)] bg-[var(--df-surface)] px-3 text-xs font-medium text-[var(--df-ink)] transition-colors duration-150 hover:border-[var(--df-border-strong)] hover:bg-[var(--df-muted)] focus-visible:ring-2 focus-visible:outline-none"
                >
                  <BookOpen
                    className="size-3.5 text-[var(--df-accent)]"
                    aria-hidden="true"
                  />
                  <span>{copy.docsLinkLabel}</span>
                </Link>
                <a
                  href="https://github.com/bytedance/deer-flow"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="focus-visible:ring-ring/50 inline-flex h-8 items-center gap-1.5 rounded-full border border-[var(--df-border)] bg-[var(--df-surface)] px-3 text-xs font-medium text-[var(--df-ink)] transition-colors duration-150 hover:border-[var(--df-border-strong)] hover:bg-[var(--df-muted)] focus-visible:ring-2 focus-visible:outline-none"
                >
                  <GitHubLogoIcon className="size-3.5" aria-hidden="true" />
                  <span>{copy.githubLinkLabel}</span>
                  <ArrowUpRight
                    className="size-3 text-[var(--df-muted-fg)]"
                    aria-hidden="true"
                  />
                </a>
              </div>
            </div>
          </div>
        </div>

        {/* Tier 2: Balanced 4-column link directory */}
        <div className="grid grid-cols-2 gap-8 pt-12 sm:grid-cols-4">
          {copy.columns.map((column) => (
            <div key={column.heading} className="flex flex-col gap-3">
              <h3 className="font-mono text-[11px] font-semibold tracking-[0.14em] text-[var(--df-ink)] uppercase">
                {column.heading}
              </h3>
              <ul className="flex flex-col gap-2.5">
                {column.links.map((link) => (
                  <li key={link.href}>
                    {link.external ? (
                      <a
                        href={link.href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="focus-visible:ring-ring/50 rounded-sm text-sm text-[var(--df-muted-fg)] transition-colors duration-150 hover:text-[var(--df-ink)] focus-visible:ring-2 focus-visible:outline-none"
                      >
                        {link.label}
                      </a>
                    ) : (
                      <Link
                        href={link.href}
                        className="focus-visible:ring-ring/50 rounded-sm text-sm text-[var(--df-muted-fg)] transition-colors duration-150 hover:text-[var(--df-ink)] focus-visible:ring-2 focus-visible:outline-none"
                      >
                        {link.label}
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        {/* Bottom bar: MIT license + ByteDance open-source attribution */}
        <div className="mt-12 flex flex-col items-center justify-between gap-2 border-t border-[var(--df-border)] pt-6 text-center text-xs text-[var(--df-muted-fg)] sm:flex-row sm:text-left">
          <p className="text-[var(--df-text-soft)]">
            {copy.license} &middot; {copy.attribution}
          </p>
          <p>&copy; {year} DeerFlow Contributors</p>
        </div>
      </div>
    </footer>
  );
}
