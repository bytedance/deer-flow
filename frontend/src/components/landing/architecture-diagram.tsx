"use client";

import {
  Bot,
  Box,
  Cpu,
  MessageSquare,
  Plug,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

export type ArchitectureLocale = "en-US" | "zh-CN";

export type ArchitectureDiagramProps = {
  className?: string;
  locale?: ArchitectureLocale;
};

type CapabilityKey =
  | "models"
  | "sandbox"
  | "skills"
  | "mcp"
  | "channels"
  | "subagents";

type TreeNodeKey =
  | "thread"
  | "models"
  | "sandbox"
  | "skills"
  | "mcp"
  | "memory"
  | "channels";

type IntegrationTile = {
  id: CapabilityKey;
  targetNode: TreeNodeKey;
  icon: LucideIcon;
  title: string;
  subtitle: string;
};

type TreeEntry = {
  id: Exclude<TreeNodeKey, "thread" | "channels">;
  path: string;
  description: string;
};

type DiagramCopy = {
  regionLabel: string;
  hubLabel: string;
  integrationsLabel: string;
  treeLabel: string;
  threadAnnotation: string;
  channelsDescription: string;
  tiles: IntegrationTile[];
  treeEntries: TreeEntry[];
};

const DIAGRAM_COPY: Record<ArchitectureLocale, DiagramCopy> = {
  "en-US": {
    regionLabel: "DeerFlow SuperAgent harness architecture",
    hubLabel: "DeerFlow Harness Core",
    integrationsLabel: "Connected capabilities",
    treeLabel: "Thread runtime hierarchy",
    threadAnnotation: "Parallel subagents",
    channelsDescription: "Web · Lark · Slack · Telegram",
    tiles: [
      {
        id: "models",
        targetNode: "models",
        icon: Cpu,
        title: "Models",
        subtitle: "LLM Routing",
      },
      {
        id: "sandbox",
        targetNode: "sandbox",
        icon: Box,
        title: "Sandboxes",
        subtitle: "Docker / K8s",
      },
      {
        id: "skills",
        targetNode: "skills",
        icon: Sparkles,
        title: "Skills",
        subtitle: "Workflows",
      },
      {
        id: "mcp",
        targetNode: "mcp",
        icon: Plug,
        title: "MCP Tools",
        subtitle: "Tool Servers",
      },
      {
        id: "channels",
        targetNode: "channels",
        icon: MessageSquare,
        title: "IM Channels",
        subtitle: "Lark / Slack / TG",
      },
      {
        id: "subagents",
        targetNode: "thread",
        icon: Bot,
        title: "Subagents",
        subtitle: "Parallel",
      },
    ],
    treeEntries: [
      {
        id: "models",
        path: "models/",
        description: "Multi-LLM routing & tools",
      },
      {
        id: "sandbox",
        path: "sandbox/",
        description: "Isolated filesystem & bash",
      },
      {
        id: "skills",
        path: "skills/",
        description: "Progressive workflows",
      },
      {
        id: "mcp",
        path: "mcp/",
        description: "Connected tool servers",
      },
      {
        id: "memory",
        path: "memory/",
        description: "Long-term user context",
      },
    ],
  },
  "zh-CN": {
    regionLabel: "DeerFlow 超级智能体引擎架构",
    hubLabel: "DeerFlow 引擎核心",
    integrationsLabel: "已接入能力模块",
    treeLabel: "线程运行时目录结构",
    threadAnnotation: "并行子智能体编排",
    channelsDescription: "Web · 飞书 · Slack · Telegram",
    tiles: [
      {
        id: "models",
        targetNode: "models",
        icon: Cpu,
        title: "模型路由",
        subtitle: "多 LLM 调度",
      },
      {
        id: "sandbox",
        targetNode: "sandbox",
        icon: Box,
        title: "隔离沙箱",
        subtitle: "Docker / K8s",
      },
      {
        id: "skills",
        targetNode: "skills",
        icon: Sparkles,
        title: "技能系统",
        subtitle: "渐进式工作流",
      },
      {
        id: "mcp",
        targetNode: "mcp",
        icon: Plug,
        title: "MCP 工具",
        subtitle: "外部工具服务",
      },
      {
        id: "channels",
        targetNode: "channels",
        icon: MessageSquare,
        title: "IM 渠道",
        subtitle: "飞书 / Slack / TG",
      },
      {
        id: "subagents",
        targetNode: "thread",
        icon: Bot,
        title: "子智能体",
        subtitle: "并行协作",
      },
    ],
    treeEntries: [
      {
        id: "models",
        path: "models/",
        description: "多模型路由与工具调用",
      },
      {
        id: "sandbox",
        path: "sandbox/",
        description: "隔离文件系统与终端",
      },
      {
        id: "skills",
        path: "skills/",
        description: "按需加载工作流",
      },
      {
        id: "mcp",
        path: "mcp/",
        description: "标准化工具服务接入",
      },
      {
        id: "memory",
        path: "memory/",
        description: "跨会话长期用户记忆",
      },
    ],
  },
};

const ARCH_ANIMATION_CSS = `
@keyframes df-arch-marquee-y {
  0% { transform: translateY(0); }
  100% { transform: translateY(-50%); }
}
@keyframes df-arch-marquee-x {
  0% { transform: translateX(0); }
  100% { transform: translateX(-50%); }
}
@keyframes df-arch-beam-slide {
  0% { transform: translateX(-100%); opacity: 0; }
  20% { opacity: 0.9; }
  80% { opacity: 0.9; }
  100% { transform: translateX(480%); opacity: 0; }
}
.df-arch-track-y {
  animation: df-arch-marquee-y 26s linear infinite;
}
.df-arch-track-x {
  animation: df-arch-marquee-x 26s linear infinite;
}
.df-arch-beam-pulse {
  animation: df-arch-beam-slide 3.6s ease-in-out infinite;
}
@media (prefers-reduced-motion: reduce) {
  .df-arch-track-y,
  .df-arch-track-x,
  .df-arch-beam-pulse {
    animation: none !important;
  }
}
`;

export function ArchitectureDiagram({
  className,
  locale = "en-US",
}: ArchitectureDiagramProps) {
  const copy = DIAGRAM_COPY[locale];
  const [selectedNode, setSelectedNode] = useState<TreeNodeKey | null>(null);
  const [hoveredNode, setHoveredNode] = useState<TreeNodeKey | null>(null);

  const activeNode = hoveredNode ?? selectedNode;

  const toggleNode = (node: TreeNodeKey) => {
    setSelectedNode((current) => (current === node ? null : node));
  };

  return (
    <div
      id="architecture"
      aria-label={copy.regionLabel}
      className={cn(
        "relative w-full min-w-0 scroll-mt-[var(--df-header-height,105px)]",
        className,
      )}
    >
      <style>{ARCH_ANIMATION_CSS}</style>

      {/* Desktop 3-part Integrations -> Hub -> Harness Tree */}
      <div className="relative hidden min-h-[360px] items-center sm:grid sm:grid-cols-[minmax(0,10.5rem)_auto_minmax(0,1fr)] sm:gap-6">
        {/* Horizontal connecting beam */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-x-10 top-1/2 z-0 h-px -translate-y-1/2 overflow-hidden bg-[color-mix(in_srgb,var(--df-accent,#0a7c93)_32%,transparent)]"
        >
          <span className="hero-beam-pulse df-arch-beam-pulse block h-full w-24 bg-gradient-to-r from-transparent via-[var(--df-accent,#0a7c93)] to-transparent" />
        </div>

        {/* Col 1: Vertical masked integration marquee */}
        <div
          aria-label={copy.integrationsLabel}
          className="hero-marquee-mask group/marquee-y relative z-10 h-[348px] overflow-hidden"
          style={{
            maskImage:
              "linear-gradient(to bottom, transparent, black 14%, black 86%, transparent)",
            WebkitMaskImage:
              "linear-gradient(to bottom, transparent, black 14%, black 86%, transparent)",
          }}
        >
          <div
            className={cn(
              "df-arch-track-y flex flex-col group-hover/marquee-y:[animation-play-state:paused]",
              selectedNode !== null && "[animation-play-state:paused]",
            )}
          >
            {[0, 1].map((pass) => (
              <div
                key={pass}
                aria-hidden={pass === 1 ? "true" : undefined}
                className="flex flex-col"
              >
                {copy.tiles.map((tile) => {
                  const Icon = tile.icon;
                  const isActive = activeNode === tile.targetNode;
                  const isDuplicate = pass === 1;
                  return (
                    <button
                      key={`${pass}-${tile.id}`}
                      type="button"
                      tabIndex={isDuplicate ? -1 : 0}
                      aria-pressed={!isDuplicate ? isActive : undefined}
                      onMouseEnter={() => setHoveredNode(tile.targetNode)}
                      onMouseLeave={() => setHoveredNode(null)}
                      onFocus={() => setHoveredNode(tile.targetNode)}
                      onBlur={() => setHoveredNode(null)}
                      onClick={() => toggleNode(tile.targetNode)}
                      className={cn(
                        "focus-visible:ring-ring/50 mb-2.5 flex h-12 w-full items-center gap-2.5 rounded-[2px] border px-2.5 text-left transition-colors duration-150 focus-visible:ring-2 focus-visible:outline-none",
                        isActive
                          ? "border-[var(--df-accent,#0a7c93)] bg-[var(--df-panel,#fffaf1)]"
                          : "border-[var(--df-border,#d8d0c2)] bg-[var(--df-surface,#fbf6ec)] hover:border-[var(--df-accent,#0a7c93)]/60 hover:bg-[var(--df-panel,#fffaf1)]",
                      )}
                    >
                      <span
                        className={cn(
                          "flex size-7 shrink-0 items-center justify-center rounded-[2px] border transition-colors duration-150",
                          isActive
                            ? "border-[var(--df-accent,#0a7c93)]/40 bg-[color-mix(in_srgb,var(--df-accent,#0a7c93)_12%,transparent)] text-[var(--df-accent,#0a7c93)]"
                            : "border-[var(--df-border-soft,#ded6c7)] bg-[var(--df-panel,#fffaf1)] text-[var(--df-text-soft,#3a352d)]",
                        )}
                      >
                        <Icon className="size-3.5" aria-hidden="true" />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-xs leading-tight font-semibold text-[var(--df-ink,#171511)]">
                          {tile.title}
                        </span>
                        <span className="block truncate font-mono text-[10px] leading-tight text-[var(--df-muted-fg,#625b50)]">
                          {tile.subtitle}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </div>

        {/* Col 2: Concentric circular DeerFlow Hub */}
        <div
          aria-label={copy.hubLabel}
          className="relative z-10 flex items-center justify-center px-2"
        >
          <div
            className={cn(
              "relative flex size-16 items-center justify-center rounded-full border bg-[var(--df-bg,#f6f2e8)] transition-colors duration-200 sm:size-20",
              activeNode !== null
                ? "border-[var(--df-accent,#0a7c93)]/70 shadow-[0_0_46px_color-mix(in_srgb,var(--df-accent,#0a7c93)_28%,transparent)]"
                : "border-[var(--df-accent,#0a7c93)]/40 shadow-[0_0_42px_color-mix(in_srgb,var(--df-accent,#0a7c93)_20%,transparent)]",
            )}
          >
            <span
              aria-hidden="true"
              className="pointer-events-none absolute -inset-3 rounded-full border border-[color-mix(in_srgb,var(--df-accent,#0a7c93)_16%,transparent)]"
            />
            <span
              aria-hidden="true"
              className="pointer-events-none absolute -inset-[22px] rounded-full border border-[color-mix(in_srgb,var(--df-accent,#0a7c93)_9%,transparent)]"
            />
            <DeerFlowEmblem className="size-8 text-[var(--df-ink,#171511)] sm:size-9" />
          </div>
        </div>

        {/* Col 3: Structured Harness Tree Card */}
        <HarnessTreeCard
          copy={copy}
          activeNode={activeNode}
          onHoverNode={setHoveredNode}
          onToggleNode={toggleNode}
        />
      </div>

      {/* Mobile stacked horizontal marquee + Harness Tree */}
      <div className="grid w-full min-w-0 gap-4 sm:hidden">
        <div
          aria-label={copy.integrationsLabel}
          className="hero-marquee-mask-x group/marquee-x relative w-full min-w-0 overflow-hidden"
          style={{
            maskImage:
              "linear-gradient(to right, transparent, black 10%, black 90%, transparent)",
            WebkitMaskImage:
              "linear-gradient(to right, transparent, black 10%, black 90%, transparent)",
          }}
        >
          <div
            className={cn(
              "df-arch-track-x flex w-max items-center group-hover/marquee-x:[animation-play-state:paused]",
              selectedNode !== null && "[animation-play-state:paused]",
            )}
          >
            {[0, 1].map((pass) => (
              <div
                key={pass}
                aria-hidden={pass === 1 ? "true" : undefined}
                className="flex shrink-0 items-center"
              >
                {copy.tiles.map((tile) => {
                  const Icon = tile.icon;
                  const isActive = activeNode === tile.targetNode;
                  const isDuplicate = pass === 1;
                  return (
                    <button
                      key={`mobile-${pass}-${tile.id}`}
                      type="button"
                      tabIndex={isDuplicate ? -1 : 0}
                      aria-pressed={!isDuplicate ? isActive : undefined}
                      onClick={() => toggleNode(tile.targetNode)}
                      className={cn(
                        "focus-visible:ring-ring/50 mr-2.5 flex h-11 shrink-0 items-center gap-2 rounded-[2px] border px-3 text-left transition-colors duration-150 focus-visible:ring-2 focus-visible:outline-none",
                        isActive
                          ? "border-[var(--df-accent,#0a7c93)] bg-[var(--df-panel,#fffaf1)]"
                          : "border-[var(--df-border,#d8d0c2)] bg-[var(--df-surface,#fbf6ec)]",
                      )}
                    >
                      <Icon
                        className={cn(
                          "size-3.5 shrink-0",
                          isActive
                            ? "text-[var(--df-accent,#0a7c93)]"
                            : "text-[var(--df-text-soft,#3a352d)]",
                        )}
                        aria-hidden="true"
                      />
                      <span className="text-xs font-semibold whitespace-nowrap text-[var(--df-ink,#171511)]">
                        {tile.title}
                      </span>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        </div>

        <HarnessTreeCard
          copy={copy}
          activeNode={activeNode}
          onHoverNode={setHoveredNode}
          onToggleNode={toggleNode}
        />
      </div>
    </div>
  );
}

function HarnessTreeCard({
  copy,
  activeNode,
  onHoverNode,
  onToggleNode,
}: {
  copy: DiagramCopy;
  activeNode: TreeNodeKey | null;
  onHoverNode: (node: TreeNodeKey | null) => void;
  onToggleNode: (node: TreeNodeKey) => void;
}) {
  return (
    <div
      aria-label={copy.treeLabel}
      className="relative z-10 w-full min-w-0 overflow-hidden rounded-[2px] border border-[var(--df-border,#d8d0c2)] bg-[var(--df-panel,#fffaf1)] p-4 text-left shadow-[0_1px_2px_var(--df-shadow,rgba(40,33,24,0.06))]"
    >
      <div className="font-mono text-xs font-semibold tracking-tight text-[var(--df-accent,#0a7c93)]">
        deerflow://
      </div>

      <div className="mt-2.5 border-l border-[var(--df-border-soft,#ded6c7)] pl-3">
        {/* thread/<thread_id>/ */}
        <button
          type="button"
          aria-pressed={activeNode === "thread"}
          onMouseEnter={() => onHoverNode("thread")}
          onMouseLeave={() => onHoverNode(null)}
          onFocus={() => onHoverNode("thread")}
          onBlur={() => onHoverNode(null)}
          onClick={() => onToggleNode("thread")}
          className={cn(
            "focus-visible:ring-ring/50 flex w-full min-w-0 flex-wrap items-baseline gap-x-2 rounded-[2px] px-1.5 py-0.5 text-left transition-colors duration-150 focus-visible:ring-2 focus-visible:outline-none",
            activeNode === "thread"
              ? "bg-[var(--df-muted,#f4edde)]"
              : "hover:bg-[var(--df-muted,#f4edde)]/70",
          )}
        >
          <span className="font-mono text-xs font-medium text-[var(--df-ink,#171511)]">
            thread/
            <span className="text-[var(--df-accent,#0a7c93)]">
              &lt;thread_id&gt;
            </span>
            /
          </span>
          <span className="text-[11px] leading-5 text-[var(--df-muted-fg,#625b50)]">
            {copy.threadAnnotation}
          </span>
        </button>

        {/* Nested thread resources */}
        <ul className="mt-1 ml-1.5 space-y-0.5 border-l border-[var(--df-border-soft,#ded6c7)] pl-3">
          {copy.treeEntries.map((entry) => {
            const isActive = activeNode === entry.id;
            return (
              <li key={entry.id} className="min-w-0">
                <button
                  type="button"
                  aria-pressed={isActive}
                  onMouseEnter={() => onHoverNode(entry.id)}
                  onMouseLeave={() => onHoverNode(null)}
                  onFocus={() => onHoverNode(entry.id)}
                  onBlur={() => onHoverNode(null)}
                  onClick={() => onToggleNode(entry.id)}
                  className={cn(
                    "focus-visible:ring-ring/50 flex w-full min-w-0 flex-wrap items-baseline gap-x-2.5 rounded-[2px] px-1.5 py-0.5 text-left transition-colors duration-150 focus-visible:ring-2 focus-visible:outline-none",
                    isActive
                      ? "bg-[var(--df-muted,#f4edde)]"
                      : "hover:bg-[var(--df-muted,#f4edde)]/70",
                  )}
                >
                  <span
                    className={cn(
                      "shrink-0 font-mono text-xs",
                      isActive
                        ? "font-semibold text-[var(--df-accent,#0a7c93)]"
                        : "text-[var(--df-ink,#171511)]",
                    )}
                  >
                    {entry.path}
                  </span>
                  <span className="min-w-0 text-[11px] leading-5 text-[var(--df-muted-fg,#625b50)]">
                    {entry.description}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>

        {/* channels/ */}
        <button
          type="button"
          aria-pressed={activeNode === "channels"}
          onMouseEnter={() => onHoverNode("channels")}
          onMouseLeave={() => onHoverNode(null)}
          onFocus={() => onHoverNode("channels")}
          onBlur={() => onHoverNode(null)}
          onClick={() => onToggleNode("channels")}
          className={cn(
            "focus-visible:ring-ring/50 mt-1.5 flex w-full min-w-0 flex-wrap items-baseline gap-x-2.5 rounded-[2px] px-1.5 py-0.5 text-left transition-colors duration-150 focus-visible:ring-2 focus-visible:outline-none",
            activeNode === "channels"
              ? "bg-[var(--df-muted,#f4edde)]"
              : "hover:bg-[var(--df-muted,#f4edde)]/70",
          )}
        >
          <span
            className={cn(
              "shrink-0 font-mono text-xs",
              activeNode === "channels"
                ? "font-semibold text-[var(--df-accent,#0a7c93)]"
                : "text-[var(--df-ink,#171511)]",
            )}
          >
            channels/
          </span>
          <span className="min-w-0 text-[11px] leading-5 text-[var(--df-muted-fg,#625b50)]">
            {copy.channelsDescription}
          </span>
        </button>
      </div>
    </div>
  );
}

function DeerFlowEmblem({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 36 36"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      className={className}
    >
      {/* Stylized minimalist geometric antler / flow mark */}
      <path
        d="M18 30V17.5M18 17.5L10.5 10.5M18 17.5L25.5 10.5"
        stroke="currentColor"
        strokeWidth="2.1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M10.5 10.5V5.5M10.5 10.5H6.5M25.5 10.5V5.5M25.5 10.5H29.5"
        stroke="currentColor"
        strokeWidth="2.1"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M14 13.8V8.2M22 13.8V8.2"
        stroke="var(--df-accent,#0a7c93)"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <circle cx="18" cy="30" r="2" fill="var(--df-accent,#0a7c93)" />
    </svg>
  );
}
