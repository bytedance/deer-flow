"use client";

import { GitHubLogoIcon } from "@radix-ui/react-icons";
import {
  ArrowUpRight,
  BookOpen,
  Box,
  ChevronDown,
  Cpu,
  FileText,
  Layers,
  MessageCircle,
  PenLine,
  Plug,
  Puzzle,
  Rocket,
  Sparkles,
  Terminal,
  Users,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { type ComponentType, type ReactNode } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  type LandingDocsLang,
  type LandingLocale,
  useOptionalLandingLocale,
} from "@/core/i18n/landing";
import { DEFAULT_LOCALE, type Locale } from "@/core/i18n/locale";
import { cn } from "@/lib/utils";

import { AnnouncementBanner } from "./announcement-banner";
import { LanguageSwitch } from "./language-switch";
import {
  MobileNav,
  type MobileNavGroup,
  type MobileNavLink,
} from "./mobile-nav";
import { StarCounter } from "./star-counter";
import { ThemeToggle } from "./theme-toggle";

export type HeaderProps = {
  className?: string;
  homeURL?: string;
  locale?: Locale;
  /** Optional search control, e.g. the docs layout's Pagefind search. */
  search?: ReactNode;
  /** Render the dismissible announcement bar inside the sticky header. */
  showBanner?: boolean;
};

type IconComponent = ComponentType<{
  className?: string;
  "aria-hidden"?: boolean;
}>;

type HeaderNavItem = {
  title: string;
  description: string;
  href: string;
  icon: IconComponent;
  external?: boolean;
};

type HeaderNavGroup = {
  id: string;
  label: string;
  eyebrow: string;
  items: HeaderNavItem[];
};

function DeerFlowMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className={cn("size-5 shrink-0", className)}
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

function getHeaderCopy(locale: LandingLocale, docsLang: LandingDocsLang) {
  const isZh = locale === "zh-CN";
  const groups: HeaderNavGroup[] = [
    {
      id: "product",
      label: isZh ? "产品" : "Product",
      eyebrow: isZh ? "核心架构" : "SUPERAGENT HARNESS",
      items: [
        {
          title: isZh ? "架构总览" : "Architecture",
          description: isZh
            ? "沙箱、记忆、技能与子智能体协同运行"
            : "Sandboxes, memory, skills, and subagents in one harness",
          href: "/#architecture",
          icon: Layers,
        },
        {
          title: isZh ? "精选案例" : "Case Studies",
          description: isZh
            ? "浏览真实可交互的 DeerFlow 演示会话"
            : "Explore live interactive DeerFlow showcase threads",
          href: "/#case-studies",
          icon: Sparkles,
        },
        {
          title: isZh ? "技能系统" : "Skills",
          description: isZh
            ? "按需渐进加载的 Markdown 领域工作流"
            : "Progressive markdown workflows loaded on demand",
          href: "/#skills",
          icon: Workflow,
        },
        {
          title: isZh ? "隔离沙箱" : "Sandbox",
          description: isZh
            ? "按线程隔离的文件系统与命令执行环境"
            : "Thread-isolated filesystem and bash execution",
          href: "/#sandbox",
          icon: Box,
        },
        {
          title: isZh ? "最新特性" : "What's New",
          description: isZh
            ? "子智能体调度、上下文工程与最新进展"
            : "Subagents, context compaction, and harness updates",
          href: "/#whats-new",
          icon: Terminal,
        },
      ],
    },
    {
      id: "integrations",
      label: isZh ? "生态集成" : "Integrations",
      eyebrow: isZh ? "工具与渠道" : "ECOSYSTEM & CHANNELS",
      items: [
        {
          title: isZh ? "模型与服务商" : "Models & Providers",
          description: isZh
            ? "兼容 OpenAI、Claude、DeepSeek 与方舟模型"
            : "Route across OpenAI, Anthropic, DeepSeek, and Ark",
          href: `/${docsLang}/docs/reference/model-providers`,
          icon: Cpu,
        },
        {
          title: isZh ? "MCP 工具" : "MCP Tools",
          description: isZh
            ? "标准 Model Context Protocol 工具服务器接入"
            : "Connect external Model Context Protocol servers",
          href: `/${docsLang}/docs/harness/mcp`,
          icon: Plug,
        },
        {
          title: isZh ? "技能生态" : "Skills Ecosystem",
          description: isZh
            ? "内置研究、文档与自定义团队工作流技能"
            : "Built-in and custom domain workflows in markdown",
          href: `/${docsLang}/docs/harness/skills`,
          icon: BookOpen,
        },
        {
          title: isZh ? "扩展与插件" : "Extensions & Plugins",
          description: isZh
            ? "面向运维可控的中间件与运行时扩展点"
            : "Operator-controlled hooks, routes, and plugins",
          href: `/${docsLang}/docs/harness/extensions`,
          icon: Puzzle,
        },
        {
          title: isZh ? "IM 渠道" : "IM Channels",
          description: isZh
            ? "通过 Gateway 接入飞书、Slack 与 Telegram"
            : "Connect Lark, Slack, and Telegram via Gateway",
          href: `/${docsLang}/docs/application/configuration`,
          icon: MessageCircle,
        },
      ],
    },
    {
      id: "developers",
      label: isZh ? "开发者" : "Developers",
      eyebrow: isZh ? "文档与开源" : "DOCS & OPEN SOURCE",
      items: [
        {
          title: isZh ? "快速开始" : "Quick Start",
          description: isZh
            ? "几分钟内完成本地或 Docker 启动"
            : "Install and run DeerFlow locally or with Docker",
          href: `/${docsLang}/docs/application/quick-start`,
          icon: Rocket,
        },
        {
          title: isZh ? "完整文档" : "Documentation",
          description: isZh
            ? "Harness 架构、配置指南与部署参考"
            : "Harness architecture, guides, and API reference",
          href: `/${docsLang}/docs`,
          icon: FileText,
        },
        {
          title: isZh ? "技术博客" : "Blog",
          description: isZh
            ? "版本发布日志与工程架构深度文章"
            : "Release notes and engineering deep dives",
          href: "/blog/posts",
          icon: PenLine,
        },
        {
          title: "GitHub",
          description: isZh
            ? "查看源代码、提交 Issue 或参与贡献"
            : "Source code, releases, and issue tracker",
          href: "https://github.com/bytedance/deer-flow",
          icon: GitHubLogoIcon,
          external: true,
        },
        {
          title: isZh ? "开源社区" : "Community",
          description: isZh
            ? "与开发者交流工作流与最佳实践"
            : "Join contributors and open-source discussions",
          href: "/#community",
          icon: Users,
        },
      ],
    },
  ];

  const mobileLinks: MobileNavLink[] = [
    {
      href: `/${docsLang}/docs/application/quick-start`,
      label: isZh ? "快速开始" : "Quick Start",
    },
    { href: `/${docsLang}/docs`, label: isZh ? "文档" : "Docs" },
    { href: "/blog/posts", label: isZh ? "博客" : "Blog" },
  ];

  const mobileGroups: MobileNavGroup[] = groups.map((group) => ({
    title: group.label,
    items: group.items.map((item) => ({
      href: item.href,
      label: item.title,
      external: item.external,
    })),
  }));

  return {
    groups,
    mobileLinks,
    mobileGroups,
    getStarted: isZh ? "开始使用" : "Get Started",
    githubAriaLabel: isZh
      ? "在 GitHub 查看 DeerFlow 仓库"
      : "DeerFlow on GitHub",
    navAriaLabel: isZh ? "主导航" : "Main navigation",
  };
}

export function Header({
  className,
  homeURL,
  locale,
  search,
  showBanner = false,
}: HeaderProps) {
  const { locale: activeLocale, docsLang } = useOptionalLandingLocale(
    locale ?? DEFAULT_LOCALE,
  );
  const copy = getHeaderCopy(activeLocale, docsLang);
  const resolvedHomeURL = homeURL ?? "/";
  const isExternalHome = /^https?:\/\//i.test(resolvedHomeURL);

  const brandContent = (
    <>
      <DeerFlowMark className="size-5 text-[var(--df-ink)] sm:size-[22px]" />
      <span className="font-landing-serif text-lg font-medium tracking-[-0.02em] whitespace-nowrap text-[var(--df-ink)] sm:text-[21px]">
        DeerFlow
      </span>
    </>
  );

  return (
    <header
      className={cn(
        "fixed inset-x-0 top-0 z-50 border-b border-[var(--df-border)] bg-[color-mix(in_oklab,var(--df-bg)_92%,transparent)] text-[var(--df-ink)] backdrop-blur-md",
        className,
      )}
    >
      {showBanner && <AnnouncementBanner locale={activeLocale} />}

      <div className="mx-auto flex h-16 max-w-[1280px] items-center justify-between gap-2 px-4 sm:gap-3 sm:px-6">
        <div className="flex min-w-0 items-center gap-6">
          {isExternalHome ? (
            <a
              href={resolvedHomeURL}
              target="_blank"
              rel="noopener noreferrer"
              className="focus-visible:ring-ring/50 inline-flex items-center gap-2 rounded-sm transition-opacity hover:opacity-80 focus-visible:ring-2 focus-visible:outline-none"
            >
              {brandContent}
            </a>
          ) : (
            <Link
              href={resolvedHomeURL}
              className="focus-visible:ring-ring/50 inline-flex items-center gap-2 rounded-sm transition-opacity hover:opacity-80 focus-visible:ring-2 focus-visible:outline-none"
            >
              {brandContent}
            </Link>
          )}

          <nav
            aria-label={copy.navAriaLabel}
            className={cn(
              "hidden items-center gap-1",
              search ? "xl:flex" : "lg:flex",
            )}
          >
            {copy.groups.map((group) => (
              <DropdownMenu key={group.id} modal={false}>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    className="focus-visible:ring-ring/50 inline-flex h-9 items-center gap-1 rounded-full px-3.5 text-sm font-medium text-[var(--df-muted-fg)] transition-colors duration-150 hover:bg-[var(--df-muted)] hover:text-[var(--df-ink)] focus-visible:ring-2 focus-visible:outline-none data-[state=open]:bg-[var(--df-muted)] data-[state=open]:text-[var(--df-ink)]"
                  >
                    <span>{group.label}</span>
                    <ChevronDown
                      className="size-3.5 opacity-70"
                      aria-hidden="true"
                    />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent
                  align="start"
                  sideOffset={10}
                  className="w-[348px] rounded-xl border border-[var(--df-border)] bg-[var(--df-panel)] p-2.5 text-[var(--df-ink)] shadow-[0_16px_40px_var(--df-shadow)]"
                >
                  <p className="mb-1.5 px-2.5 pt-1 font-mono text-[10px] font-medium tracking-[0.16em] text-[var(--df-muted-fg)] uppercase">
                    {group.eyebrow}
                  </p>
                  <div className="flex flex-col gap-0.5">
                    {group.items.map((item) => {
                      const Icon = item.icon;
                      const itemInner = (
                        <>
                          <span className="mt-0.5 inline-flex size-8 shrink-0 items-center justify-center rounded-lg bg-[var(--df-accent-soft)] text-[var(--df-accent)]">
                            <Icon className="size-4" aria-hidden={true} />
                          </span>
                          <span className="flex min-w-0 flex-col gap-0.5 text-left">
                            <span className="inline-flex items-center gap-1 text-sm font-medium text-[var(--df-ink)]">
                              <span>{item.title}</span>
                              {item.external && (
                                <ArrowUpRight
                                  className="size-3 text-[var(--df-muted-fg)]"
                                  aria-hidden="true"
                                />
                              )}
                            </span>
                            <span className="line-clamp-2 text-xs leading-4 text-[var(--df-muted-fg)]">
                              {item.description}
                            </span>
                          </span>
                        </>
                      );

                      return (
                        <DropdownMenuItem
                          key={item.href}
                          asChild
                          className="flex items-start gap-3 rounded-lg px-2.5 py-2 text-left transition-colors focus:bg-[var(--df-muted)] focus:text-[var(--df-ink)]"
                        >
                          {item.external ? (
                            <a
                              href={item.href}
                              target="_blank"
                              rel="noopener noreferrer"
                            >
                              {itemInner}
                            </a>
                          ) : (
                            <Link href={item.href}>{itemInner}</Link>
                          )}
                        </DropdownMenuItem>
                      );
                    })}
                  </div>
                </DropdownMenuContent>
              </DropdownMenu>
            ))}
          </nav>
        </div>

        <div className="flex shrink-0 items-center gap-1 sm:gap-1.5">
          {search && (
            <div className="hidden w-40 sm:block lg:w-52">{search}</div>
          )}

          <a
            href="https://github.com/bytedance/deer-flow"
            target="_blank"
            rel="noopener noreferrer"
            aria-label={copy.githubAriaLabel}
            className="group focus-visible:ring-ring/50 hidden h-9 items-center gap-1.5 rounded-full border border-[var(--df-border)] bg-[var(--df-panel)] px-3 text-xs font-medium text-[var(--df-ink)] transition-colors duration-150 hover:border-[var(--df-border-strong)] hover:bg-[var(--df-muted)] focus-visible:ring-2 focus-visible:outline-none sm:inline-flex"
          >
            <GitHubLogoIcon className="size-4 shrink-0" aria-hidden="true" />
            <StarCounter />
          </a>

          <LanguageSwitch locale={activeLocale} />
          <ThemeToggle locale={activeLocale} />

          <Link
            href="/workspace/chats/new"
            className="focus-visible:ring-ring/50 hidden h-9 items-center justify-center rounded-full bg-[var(--df-cta)] px-4 text-xs font-medium whitespace-nowrap text-[var(--df-cta-fg)] transition-colors duration-150 hover:bg-[var(--df-cta-hover)] focus-visible:ring-2 focus-visible:outline-none md:inline-flex"
          >
            {copy.getStarted}
          </Link>

          <MobileNav
            links={copy.mobileLinks}
            groups={copy.mobileGroups}
            search={search}
            locale={activeLocale}
            triggerClassName={search ? "xl:hidden" : "lg:hidden"}
            showActions
          />
        </div>
      </div>
    </header>
  );
}
