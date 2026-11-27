"use client";

import {
  Box,
  Cpu,
  Globe,
  Layers,
  MessageSquare,
  Plug,
  Sparkles,
  Terminal,
  Webhook,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { type KeyboardEvent, useId, useRef, useState } from "react";

import { cn } from "@/lib/utils";

export type ArchitectureLocale = "en-US" | "zh-CN";

export type ArchitectureDiagramProps = {
  className?: string;
  locale?: ArchitectureLocale;
};

export type WorkflowModeId = "research" | "sandbox" | "im-bot";
type EntryId = "web" | "im" | "api";
type EngineId = "lead" | "subagents";
type ModuleId = "models" | "sandboxes" | "skills" | "mcp";

type WorkflowModeConfig = {
  id: WorkflowModeId;
  label: string;
  harnessStatus: string;
  activeEntry: EntryId;
  activeEngines: EngineId[];
  activeModules: ModuleId[];
  trace: string;
};

type EntryNode = {
  id: EntryId;
  modeId: WorkflowModeId;
  icon: LucideIcon;
  title: string;
  subtitle: string;
};

type EngineBlock = {
  id: EngineId;
  icon: LucideIcon;
  title: string;
  subtitle: string;
};

type ExecutionModule = {
  id: ModuleId;
  icon: LucideIcon;
  title: string;
  subtitle: string;
  inspectTrace: string;
};

type BlueprintCopy = {
  regionLabel: string;
  headerTitle: string;
  tablistLabel: string;
  tier1Label: string;
  tier2Badge: string;
  tier3Label: string;
  tracePrefix: string;
  modulePrefix: string;
  modes: WorkflowModeConfig[];
  entries: EntryNode[];
  engines: EngineBlock[];
  modules: ExecutionModule[];
};

const ENTRY_X: Record<EntryId, number> = {
  web: 100,
  im: 300,
  api: 500,
};

const MODULE_X: Record<ModuleId, number> = {
  models: 75,
  sandboxes: 225,
  skills: 375,
  mcp: 525,
};

const BLUEPRINT_COPY: Record<ArchitectureLocale, BlueprintCopy> = {
  "en-US": {
    regionLabel: "DeerFlow 3-tier agent harness architecture blueprint",
    headerTitle: "HARNESS ARCHITECTURE",
    tablistLabel: "Workflow execution modes",
    tier1Label: "01 · ENTRY & TRIGGERS",
    tier2Badge: "DEERFLOW HARNESS · THREAD-ISOLATED RUNTIME",
    tier3Label: "03 · PLUG-IN EXECUTION PLANE",
    tracePrefix: "trace ›",
    modulePrefix: "module ›",
    modes: [
      {
        id: "research",
        label: "Research",
        harnessStatus: "FAN-OUT · PARALLEL",
        activeEntry: "web",
        activeEngines: ["lead", "subagents"],
        activeModules: ["models", "skills", "mcp"],
        trace:
          "load skill:deep-research → spawn 2 subagents → mcp:web-search → deliver report",
      },
      {
        id: "sandbox",
        label: "Code & Sandbox",
        harnessStatus: "ISOLATED EXEC",
        activeEntry: "api",
        activeEngines: ["lead", "subagents"],
        activeModules: ["models", "sandboxes", "skills"],
        trace:
          "mount /mnt/user-data → load skill:code-review → sandbox:exec tests → export artifact",
      },
      {
        id: "im-bot",
        label: "IM Bot",
        harnessStatus: "THREAD MEMORY",
        activeEntry: "im",
        activeEngines: ["lead"],
        activeModules: ["models", "mcp"],
        trace:
          "lark:mention → recall thread memory → mcp:issue-tracker → stream reply in thread",
      },
    ],
    entries: [
      {
        id: "web",
        modeId: "research",
        icon: Globe,
        title: "Web Workspace",
        subtitle: "Chat & Artifacts",
      },
      {
        id: "im",
        modeId: "im-bot",
        icon: MessageSquare,
        title: "IM Channels",
        subtitle: "Lark · Slack · TG",
      },
      {
        id: "api",
        modeId: "sandbox",
        icon: Webhook,
        title: "API & Schedules",
        subtitle: "Gateway · Cron",
      },
    ],
    engines: [
      {
        id: "lead",
        icon: Workflow,
        title: "Lead Agent Loop",
        subtitle: "Model Router · Context Compaction · Memory",
      },
      {
        id: "subagents",
        icon: Layers,
        title: "Subagent Orchestrator",
        subtitle: "Parallel Workers · Task Delegation",
      },
    ],
    modules: [
      {
        id: "models",
        icon: Cpu,
        title: "Models",
        subtitle: "Multi-LLM",
        inspectTrace:
          "models: route reasoning & fast tiers across OpenAI, Anthropic, DeepSeek & local endpoints",
      },
      {
        id: "sandboxes",
        icon: Box,
        title: "Sandboxes",
        subtitle: "Docker / K8s / Local",
        inspectTrace:
          "sandboxes: thread-isolated bash runtime with /mnt/user-data workspace, uploads & outputs",
      },
      {
        id: "skills",
        icon: Sparkles,
        title: "Skills",
        subtitle: "Progressive SKILL.md",
        inspectTrace:
          "skills: index lightweight manifests first, inject full workflow instructions only on match",
      },
      {
        id: "mcp",
        icon: Plug,
        title: "MCP Tools",
        subtitle: "External Servers",
        inspectTrace:
          "mcp: attach stdio & SSE external tool servers with scoped per-thread execution",
      },
    ],
  },
  "zh-CN": {
    regionLabel: "DeerFlow 三层智能体引擎架构蓝图",
    headerTitle: "引擎架构视图",
    tablistLabel: "工作流运行模式",
    tier1Label: "01 · 入口与触发层",
    tier2Badge: "DEERFLOW 引擎 · 线程隔离运行时",
    tier3Label: "03 · 插件化执行平面",
    tracePrefix: "trace ›",
    modulePrefix: "module ›",
    modes: [
      {
        id: "research",
        label: "深度研究",
        harnessStatus: "并行扇出",
        activeEntry: "web",
        activeEngines: ["lead", "subagents"],
        activeModules: ["models", "skills", "mcp"],
        trace:
          "加载 skill:deep-research → 派生 2 个并行子智能体 → mcp:检索信息 → 生成研究报告",
      },
      {
        id: "sandbox",
        label: "代码与沙箱",
        harnessStatus: "隔离执行",
        activeEntry: "api",
        activeEngines: ["lead", "subagents"],
        activeModules: ["models", "sandboxes", "skills"],
        trace:
          "挂载 /mnt/user-data → 加载代码技能 → sandbox:运行测试 → 导出构建产物",
      },
      {
        id: "im-bot",
        label: "IM 机器人",
        harnessStatus: "会话记忆",
        activeEntry: "im",
        activeEngines: ["lead"],
        activeModules: ["models", "mcp"],
        trace:
          "飞书:@提及 → 召回跨会话记忆 → mcp:查询外部服务 → 线程内流式回复",
      },
    ],
    entries: [
      {
        id: "web",
        modeId: "research",
        icon: Globe,
        title: "Web 工作台",
        subtitle: "对话与产物",
      },
      {
        id: "im",
        modeId: "im-bot",
        icon: MessageSquare,
        title: "IM 渠道",
        subtitle: "飞书 · Slack · TG",
      },
      {
        id: "api",
        modeId: "sandbox",
        icon: Webhook,
        title: "API 与定时任务",
        subtitle: "Gateway · Cron",
      },
    ],
    engines: [
      {
        id: "lead",
        icon: Workflow,
        title: "主智能体循环",
        subtitle: "模型路由 · 上下文压缩 · 长期记忆",
      },
      {
        id: "subagents",
        icon: Layers,
        title: "子智能体编排器",
        subtitle: "并行工作节点 · 任务委派",
      },
    ],
    modules: [
      {
        id: "models",
        icon: Cpu,
        title: "模型路由",
        subtitle: "多模型调度",
        inspectTrace:
          "models: 灵活路由多厂商大语言模型与本地推理端点，按任务阶段匹配推理能力",
      },
      {
        id: "sandboxes",
        icon: Box,
        title: "隔离沙箱",
        subtitle: "Docker / K8s / 本地",
        inspectTrace:
          "sandboxes: 为每个线程提供独立文件系统与终端环境，安全隔离代码与数据",
      },
      {
        id: "skills",
        icon: Sparkles,
        title: "技能系统",
        subtitle: "渐进式 SKILL.md",
        inspectTrace:
          "skills: 先索引轻量元数据，命中任务时再按需注入完整工作流指令",
      },
      {
        id: "mcp",
        icon: Plug,
        title: "MCP 工具",
        subtitle: "外部工具服务",
        inspectTrace:
          "mcp: 标准化接入 stdio 与 SSE 外部工具服务，扩展数据源与业务系统能力",
      },
    ],
  },
};

export function ArchitectureDiagram({
  className,
  locale = "en-US",
}: ArchitectureDiagramProps) {
  const idPrefix = useId();
  const panelId = `${idPrefix}-panel`;
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const copy = BLUEPRINT_COPY[locale];
  const [activeModeId, setActiveModeId] = useState<WorkflowModeId>("research");
  const [inspectedModuleId, setInspectedModuleId] = useState<ModuleId | null>(
    null,
  );

  const activeMode =
    copy.modes.find((mode) => mode.id === activeModeId) ?? copy.modes[0]!;
  const inspectedModule = inspectedModuleId
    ? (copy.modules.find((mod) => mod.id === inspectedModuleId) ?? null)
    : null;

  const highlightedModules: ModuleId[] = inspectedModule
    ? [inspectedModule.id]
    : activeMode.activeModules;

  const handleSelectMode = (modeId: WorkflowModeId) => {
    setActiveModeId(modeId);
    setInspectedModuleId(null);
  };

  const handleTabKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    currentIndex: number,
  ) => {
    const count = copy.modes.length;
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight") {
      nextIndex = (currentIndex + 1) % count;
    } else if (event.key === "ArrowLeft") {
      nextIndex = (currentIndex - 1 + count) % count;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = count - 1;
    }
    if (nextIndex === null) return;
    event.preventDefault();
    const nextMode = copy.modes[nextIndex];
    if (!nextMode) return;
    handleSelectMode(nextMode.id);
    tabRefs.current[nextIndex]?.focus();
  };

  const handleToggleModule = (moduleId: ModuleId) => {
    setInspectedModuleId((current) => (current === moduleId ? null : moduleId));
  };

  return (
    <div
      id="architecture"
      role="region"
      aria-label={copy.regionLabel}
      className={cn(
        "relative w-full min-w-0 scroll-mt-[var(--df-header-height,100px)] overflow-hidden rounded-2xl border border-[var(--df-border)] bg-[var(--df-panel)] text-left shadow-[0_12px_36px_var(--df-shadow)]",
        className,
      )}
    >
      {/* Top Schematic Bar */}
      <div className="flex flex-wrap items-center justify-between gap-2.5 border-b border-[var(--df-border)] bg-[var(--df-bg-soft)] px-3.5 py-3 sm:px-4">
        <div className="flex min-w-0 items-center gap-2">
          <span
            aria-hidden="true"
            className="size-2 shrink-0 rounded-full bg-[var(--df-accent)]"
          />
          <span className="truncate font-mono text-[11px] font-semibold tracking-[0.14em] text-[var(--df-text-soft)] uppercase">
            {copy.headerTitle}
          </span>
        </div>

        <div
          role="tablist"
          aria-label={copy.tablistLabel}
          className="flex flex-wrap items-center gap-1 rounded-lg border border-[var(--df-border)] bg-[var(--df-surface)] p-0.5"
        >
          {copy.modes.map((mode, index) => {
            const isSelected = mode.id === activeMode.id;
            return (
              <button
                key={mode.id}
                ref={(el) => {
                  tabRefs.current[index] = el;
                }}
                id={`${idPrefix}-tab-${mode.id}`}
                type="button"
                role="tab"
                aria-selected={isSelected}
                aria-controls={panelId}
                tabIndex={isSelected ? 0 : -1}
                onClick={() => handleSelectMode(mode.id)}
                onKeyDown={(event) => handleTabKeyDown(event, index)}
                className={cn(
                  "focus-visible:ring-ring/50 min-h-8 rounded-md px-2.5 py-1 text-xs font-medium whitespace-nowrap transition-colors duration-150 focus-visible:ring-2 focus-visible:outline-none",
                  isSelected
                    ? "bg-[var(--df-cta)] text-[var(--df-cta-fg)] shadow-xs"
                    : "text-[var(--df-muted-fg)] hover:bg-[var(--df-muted)]/70 hover:text-[var(--df-ink)]",
                )}
              >
                {mode.label}
              </button>
            );
          })}
        </div>
      </div>

      <div
        id={panelId}
        role="tabpanel"
        aria-labelledby={`${idPrefix}-tab-${activeMode.id}`}
      >
        {/* 3-Tier Blueprint Canvas */}
        <div className="p-3.5 sm:p-5">
          {/* Tier 1: Entry & Triggers */}
          <div>
            <div className="mb-2 font-mono text-[10px] font-medium tracking-[0.14em] text-[var(--df-muted-fg)] uppercase">
              {copy.tier1Label}
            </div>
            <div className="grid grid-cols-3 gap-1.5 sm:gap-2.5">
              {copy.entries.map((entry) => {
                const Icon = entry.icon;
                const isActive = activeMode.activeEntry === entry.id;
                return (
                  <button
                    key={entry.id}
                    type="button"
                    data-node-id={`entry-${entry.id}`}
                    data-active={isActive ? "true" : "false"}
                    aria-pressed={isActive}
                    onClick={() => handleSelectMode(entry.modeId)}
                    className={cn(
                      "focus-visible:ring-ring/50 flex min-w-0 flex-col items-start gap-1.5 rounded-xl border px-2.5 py-2.5 text-left transition-all duration-150 focus-visible:ring-2 focus-visible:outline-none sm:flex-row sm:items-center sm:gap-2.5 sm:px-3",
                      isActive
                        ? "border-[var(--df-accent)] bg-[var(--df-accent-soft,rgba(28,93,74,0.09))] shadow-[0_2px_10px_var(--df-shadow)]"
                        : "border-[var(--df-border)] bg-[var(--df-surface)] hover:border-[var(--df-border-strong)] hover:bg-[var(--df-bg-soft)]",
                    )}
                  >
                    <span
                      className={cn(
                        "flex size-7 shrink-0 items-center justify-center rounded-lg border transition-colors duration-150",
                        isActive
                          ? "border-[var(--df-accent)]/35 bg-[var(--df-panel)] text-[var(--df-accent)]"
                          : "border-[var(--df-border-soft)] bg-[var(--df-panel)] text-[var(--df-muted-fg)]",
                      )}
                    >
                      <Icon className="size-3.5" aria-hidden="true" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[11px] leading-tight font-semibold text-[var(--df-ink)] sm:text-xs">
                        {entry.title}
                      </span>
                      <span className="mt-0.5 hidden truncate font-mono text-[10px] leading-tight text-[var(--df-muted-fg)] sm:block">
                        {entry.subtitle}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Orthogonal SVG Flow Connectors: Tier 1 -> Tier 2 */}
          <TopBusConnectors activeEntry={activeMode.activeEntry} />

          {/* Tier 2: DeerFlow LangGraph Harness */}
          <div
            data-testid="architecture-harness-core"
            className="rounded-xl border border-[var(--df-accent)]/40 bg-[var(--df-accent-soft,rgba(28,93,74,0.07))] p-3 sm:p-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <DeerFlowBlueprintMark className="size-4 shrink-0 text-[var(--df-accent)]" />
                <span className="font-mono text-[10px] font-semibold tracking-[0.12em] text-[var(--df-accent)] uppercase sm:text-[11px]">
                  {copy.tier2Badge}
                </span>
              </div>
              <span className="rounded-full border border-[var(--df-accent)]/30 bg-[var(--df-panel)] px-2 py-0.5 font-mono text-[10px] font-medium tracking-wide text-[var(--df-accent)]">
                {activeMode.harnessStatus}
              </span>
            </div>

            <div className="mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
              {copy.engines.map((engine) => {
                const Icon = engine.icon;
                const isActive = activeMode.activeEngines.includes(engine.id);
                return (
                  <div
                    key={engine.id}
                    data-node-id={`engine-${engine.id}`}
                    data-active={isActive ? "true" : "false"}
                    className={cn(
                      "flex min-w-0 items-start gap-2.5 rounded-lg border px-3 py-2.5 transition-all duration-150",
                      isActive
                        ? "border-[var(--df-accent)]/60 bg-[var(--df-panel)] shadow-[0_2px_10px_var(--df-shadow)]"
                        : "border-[var(--df-border)] bg-[var(--df-panel)]/70 opacity-75",
                    )}
                  >
                    <span
                      className={cn(
                        "mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md border",
                        isActive
                          ? "border-[var(--df-accent)]/35 bg-[var(--df-accent-soft,rgba(28,93,74,0.09))] text-[var(--df-accent)]"
                          : "border-[var(--df-border-soft)] bg-[var(--df-surface)] text-[var(--df-muted-fg)]",
                      )}
                    >
                      <Icon className="size-3.5" aria-hidden="true" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs font-semibold text-[var(--df-ink)]">
                          {engine.title}
                        </span>
                        {isActive && (
                          <span
                            aria-hidden="true"
                            className="size-1.5 shrink-0 rounded-full bg-[var(--df-accent)]"
                          />
                        )}
                      </div>
                      <p className="mt-0.5 font-mono text-[10px] leading-relaxed text-[var(--df-muted-fg)]">
                        {engine.subtitle}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Orthogonal SVG Bus Connectors: Tier 2 -> Tier 3 */}
          <BottomBusConnectors activeModules={highlightedModules} />

          {/* Tier 3: Plug-in Execution Plane */}
          <div>
            <div className="mb-2 font-mono text-[10px] font-medium tracking-[0.14em] text-[var(--df-muted-fg)] uppercase">
              {copy.tier3Label}
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 sm:gap-2.5">
              {copy.modules.map((mod) => {
                const Icon = mod.icon;
                const isHighlighted = highlightedModules.includes(mod.id);
                const isInspected = inspectedModuleId === mod.id;
                return (
                  <button
                    key={mod.id}
                    type="button"
                    data-node-id={`module-${mod.id}`}
                    data-active={isHighlighted ? "true" : "false"}
                    aria-pressed={isInspected}
                    onClick={() => handleToggleModule(mod.id)}
                    className={cn(
                      "focus-visible:ring-ring/50 flex min-w-0 flex-col items-start rounded-xl border px-3 py-2.5 text-left transition-all duration-150 focus-visible:ring-2 focus-visible:outline-none",
                      isInspected
                        ? "border-[var(--df-accent)] bg-[var(--df-accent-soft,rgba(28,93,74,0.1))] ring-1 ring-[var(--df-accent)]/40"
                        : isHighlighted
                          ? "border-[var(--df-accent)]/60 bg-[var(--df-panel)] shadow-[0_2px_10px_var(--df-shadow)]"
                          : "border-[var(--df-border)] bg-[var(--df-surface)] hover:border-[var(--df-border-strong)] hover:bg-[var(--df-bg-soft)]",
                    )}
                  >
                    <div className="flex w-full items-center justify-between gap-1.5">
                      <span
                        className={cn(
                          "flex size-6 shrink-0 items-center justify-center rounded-md border",
                          isHighlighted
                            ? "border-[var(--df-accent)]/35 bg-[var(--df-accent-soft,rgba(28,93,74,0.09))] text-[var(--df-accent)]"
                            : "border-[var(--df-border-soft)] bg-[var(--df-panel)] text-[var(--df-muted-fg)]",
                        )}
                      >
                        <Icon className="size-3.5" aria-hidden="true" />
                      </span>
                      <span
                        aria-hidden="true"
                        className={cn(
                          "size-1.5 rounded-full transition-colors",
                          isHighlighted
                            ? "bg-[var(--df-accent)]"
                            : "bg-[var(--df-border-strong)]/60",
                        )}
                      />
                    </div>
                    <span className="mt-2 block w-full truncate text-xs font-semibold text-[var(--df-ink)]">
                      {mod.title}
                    </span>
                    <span className="mt-0.5 block w-full truncate font-mono text-[10px] text-[var(--df-muted-fg)]">
                      {mod.subtitle}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        {/* Bottom Execution Trace Strip */}
        <div
          data-testid="architecture-trace"
          aria-live="polite"
          className="flex items-start gap-2 border-t border-[var(--df-border)] bg-[var(--df-bg-soft)] px-3.5 py-2.5 font-mono text-[11px] leading-relaxed text-[var(--df-text-soft)] sm:px-4 sm:text-xs"
        >
          <Terminal
            className="mt-0.5 size-3.5 shrink-0 text-[var(--df-accent)]"
            aria-hidden="true"
          />
          <p className="min-w-0 flex-1 break-words">
            <span className="mr-1.5 font-semibold text-[var(--df-accent)]">
              {inspectedModule ? copy.modulePrefix : copy.tracePrefix}
            </span>
            <span>
              {inspectedModule
                ? inspectedModule.inspectTrace
                : activeMode.trace}
            </span>
          </p>
        </div>
      </div>
    </div>
  );
}

function TopBusConnectors({ activeEntry }: { activeEntry: EntryId }) {
  const activeX = ENTRY_X[activeEntry];
  const activePath =
    activeX === 300 ? "M 300 2 V 32" : `M ${activeX} 2 V 17 H 300 V 32`;

  return (
    <svg
      viewBox="0 0 600 34"
      fill="none"
      aria-hidden="true"
      className="block h-7 w-full sm:h-8"
    >
      {/* Inactive structural bus lines */}
      <path
        d="M 100 2 V 17 H 500 V 2"
        stroke="var(--df-border-strong)"
        strokeWidth="1.25"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.55"
      />
      <path
        d="M 300 2 V 32"
        stroke="var(--df-border-strong)"
        strokeWidth="1.25"
        strokeLinecap="round"
        opacity="0.55"
      />
      {/* Active route highlight */}
      <path
        d={activePath}
        stroke="var(--df-accent)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.45"
      />
      <path
        d={activePath}
        stroke="var(--df-accent)"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeDasharray="5 6"
        className="df-flow-dash"
      />
      {/* Terminal nodes */}
      {(Object.entries(ENTRY_X) as [EntryId, number][]).map(([id, x]) => (
        <circle
          key={id}
          cx={x}
          cy={3}
          r={id === activeEntry ? 3 : 2.25}
          fill={
            id === activeEntry ? "var(--df-accent)" : "var(--df-border-strong)"
          }
        />
      ))}
      <circle cx={300} cy={31} r={3} fill="var(--df-accent)" />
    </svg>
  );
}

function BottomBusConnectors({ activeModules }: { activeModules: ModuleId[] }) {
  return (
    <svg
      viewBox="0 0 600 34"
      fill="none"
      aria-hidden="true"
      className="block h-7 w-full sm:h-8"
    >
      {/* Base structural distribution bus */}
      <path
        d="M 300 2 V 17"
        stroke="var(--df-border-strong)"
        strokeWidth="1.25"
        strokeLinecap="round"
        opacity="0.55"
      />
      <path
        d="M 75 32 V 17 H 525 V 32"
        stroke="var(--df-border-strong)"
        strokeWidth="1.25"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.55"
      />
      <path
        d="M 225 17 V 32 M 375 17 V 32"
        stroke="var(--df-border-strong)"
        strokeWidth="1.25"
        strokeLinecap="round"
        opacity="0.55"
      />

      {/* Highlighted active branches */}
      {activeModules.map((moduleId) => {
        const targetX = MODULE_X[moduleId];
        const branchPath = `M 300 2 V 17 H ${targetX} V 32`;
        return (
          <g key={moduleId}>
            <path
              d={branchPath}
              stroke="var(--df-accent)"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              opacity="0.4"
            />
            <path
              d={branchPath}
              stroke="var(--df-accent)"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeDasharray="5 6"
              className="df-flow-dash"
            />
          </g>
        );
      })}

      {/* Bus terminals */}
      <circle cx={300} cy={3} r={3} fill="var(--df-accent)" />
      {(Object.entries(MODULE_X) as [ModuleId, number][]).map(([id, x]) => {
        const isActive = activeModules.includes(id);
        return (
          <circle
            key={id}
            cx={x}
            cy={31}
            r={isActive ? 3 : 2.25}
            fill={isActive ? "var(--df-accent)" : "var(--df-border-strong)"}
          />
        );
      })}
    </svg>
  );
}

function DeerFlowBlueprintMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      className={className}
    >
      <path
        d="M12 20V11.5M12 11.5L7 6.8M12 11.5L17 6.8"
        stroke="currentColor"
        strokeWidth="1.9"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M7 6.8V3.5M7 6.8H4.2M17 6.8V3.5M17 6.8H19.8"
        stroke="currentColor"
        strokeWidth="1.9"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="12" cy="20" r="1.7" fill="currentColor" />
    </svg>
  );
}
