"use client";

import {
  BarChart3Icon,
  ChevronRightIcon,
  LayoutDashboardIcon,
  MoreVerticalIcon,
  SendIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import { useThreads } from "@/core/threads/hooks";
import { titleOfThread } from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

const TEMPLATE_CATEGORIES = [
  "Featured",
  "Finance and Investments",
  "Project and Event Management",
  "Data analysis",
  "Personal Productivity",
  "Education & Training",
] as const;

interface Template {
  id: string;
  name: string;
  description: string;
  category: string;
  prompt: string;
  colors: string[];
}

const TEMPLATES: Template[] = [
  {
    id: "business-infographic",
    name: "Business Infographic",
    description: "Key business metrics dashboard",
    category: "Featured",
    prompt: "Create a business infographic dashboard with key metrics like revenue, growth rate, customer acquisition, and market share. Use professional charts and visualizations.",
    colors: ["#2563eb", "#7c3aed", "#06b6d4"],
  },
  {
    id: "market-analysis",
    name: "Market Analysis",
    description: "Market trends and competitive analysis",
    category: "Featured",
    prompt: "Create a market analysis dashboard showing market size, growth trends, competitor market share, and key industry metrics with pie charts and trend lines.",
    colors: ["#059669", "#10b981", "#34d399"],
  },
  {
    id: "chart-infographic",
    name: "Chart Infographic",
    description: "Multi-chart data presentation",
    category: "Featured",
    prompt: "Create an infographic-style dashboard with multiple chart types: bar charts, line charts, and donut charts showing sample business data with colorful styling.",
    colors: ["#f59e0b", "#ef4444", "#8b5cf6"],
  },
  {
    id: "cycle-info",
    name: "Cycle Infographic",
    description: "Process and cycle visualization",
    category: "Featured",
    prompt: "Create a cycle/process infographic showing a business workflow with connected stages, progress indicators, and supporting metrics.",
    colors: ["#06b6d4", "#3b82f6", "#8b5cf6"],
  },
  {
    id: "banners-infographic",
    name: "Banners Infographic",
    description: "KPI banners and summary cards",
    category: "Featured",
    prompt: "Create a dashboard with prominent KPI banner cards showing revenue ($12,394), profit ($15,016), and expenses ($51,627) with comparison charts and trend indicators.",
    colors: ["#ef4444", "#22c55e", "#3b82f6"],
  },
  {
    id: "statistical-infographic",
    name: "Statistical Infographic",
    description: "Statistical data visualization",
    category: "Featured",
    prompt: "Create a statistical dashboard showing percentages (70%, 80%), progress bars, data distributions, and trend charts with a clean professional layout.",
    colors: ["#0ea5e9", "#14b8a6", "#6366f1"],
  },
  {
    id: "financial-overview",
    name: "Financial Overview",
    description: "Revenue, expenses, and profit trends",
    category: "Finance and Investments",
    prompt: "Create a financial overview dashboard with revenue vs expenses line chart, profit margins, cash flow waterfall chart, and quarterly comparison.",
    colors: ["#059669", "#0ea5e9", "#f59e0b"],
  },
  {
    id: "project-tracker",
    name: "Project Tracker",
    description: "Project progress and milestones",
    category: "Project and Event Management",
    prompt: "Create a project management dashboard showing project timeline, task completion rates, team workload distribution, and milestone tracking.",
    colors: ["#8b5cf6", "#ec4899", "#f97316"],
  },
  {
    id: "data-exploration",
    name: "Data Exploration",
    description: "Exploratory data analysis template",
    category: "Data analysis",
    prompt: "Create a data exploration dashboard with distribution histograms, correlation scatter plots, summary statistics cards, and a data quality overview.",
    colors: ["#3b82f6", "#10b981", "#f59e0b"],
  },
  {
    id: "productivity-dashboard",
    name: "Productivity Dashboard",
    description: "Personal productivity metrics",
    category: "Personal Productivity",
    prompt: "Create a personal productivity dashboard showing daily task completion, focus time tracking, weekly goals progress, and habit streaks with motivational metrics.",
    colors: ["#8b5cf6", "#06b6d4", "#22c55e"],
  },
  {
    id: "learning-analytics",
    name: "Learning Analytics",
    description: "Education and training metrics",
    category: "Education & Training",
    prompt: "Create an education analytics dashboard with course completion rates, student performance distribution, engagement metrics, and learning path progress.",
    colors: ["#f59e0b", "#ef4444", "#3b82f6"],
  },
];

function TemplateCard({ template, onClick }: { template: Template; onClick: () => void }) {
  return (
    <button
      className="group flex w-48 shrink-0 flex-col overflow-hidden rounded-xl border bg-card transition-shadow hover:shadow-lg"
      onClick={onClick}
    >
      <div
        className="flex h-28 items-center justify-center p-3"
        style={{
          background: `linear-gradient(135deg, ${template.colors[0]}15, ${template.colors[1]}20, ${template.colors[2]}10)`,
        }}
      >
        <div className="flex gap-2">
          {template.colors.map((color, i) => (
            <div key={i} className="flex flex-col gap-1">
              <div
                className="h-8 rounded"
                style={{ backgroundColor: color, width: `${20 + i * 8}px`, opacity: 0.7 + i * 0.1 }}
              />
              <div
                className="h-4 rounded"
                style={{ backgroundColor: color, width: `${16 + i * 4}px`, opacity: 0.5 }}
              />
            </div>
          ))}
        </div>
      </div>
      <div className="p-3">
        <p className="text-left text-xs font-medium">{template.name}</p>
      </div>
    </button>
  );
}

export default function GraphsHomePage() {
  const { t } = useI18n();
  const router = useRouter();
  const { data: threads } = useThreads();
  const [prompt, setPrompt] = useState("");
  const [activeCategory, setActiveCategory] = useState<string>("Featured");

  useEffect(() => {
    document.title = `AI Graphs - ${t.pages.appName}`;
  }, [t.pages.appName]);

  const filteredTemplates = useMemo(
    () => TEMPLATES.filter((tmpl) => tmpl.category === activeCategory),
    [activeCategory],
  );

  const handleSubmit = useCallback(
    (text?: string) => {
      const msg = text ?? prompt;
      if (!msg.trim()) return;
      // Store the initial prompt so the graphs page can pick it up
      sessionStorage.setItem("graphs-initial-prompt", msg);
      router.push("/workspace/graphs/new");
    },
    [prompt, router],
  );

  const handleTemplateClick = useCallback(
    (template: Template) => {
      handleSubmit(template.prompt);
    },
    [handleSubmit],
  );

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="flex size-full flex-col overflow-auto">
          {/* Hero + Prompt */}
          <div className="mx-auto flex w-full max-w-3xl flex-col items-center px-6 pt-12 pb-8">
            <div className="flex items-center gap-2 text-2xl font-semibold">
              <LayoutDashboardIcon className="size-6" />
              <span>What would you like to visualize?</span>
            </div>

            <div className="mt-6 w-full">
              <div className="flex items-center gap-2 rounded-xl border bg-card px-4 py-3 shadow-sm focus-within:ring-2 focus-within:ring-primary/20">
                <input
                  className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                  placeholder="Ask anything ..."
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleSubmit();
                    }
                  }}
                />
                <Button
                  size="icon-sm"
                  className="shrink-0 rounded-full"
                  disabled={!prompt.trim()}
                  onClick={() => handleSubmit()}
                >
                  <SendIcon className="size-3.5" />
                </Button>
              </div>
            </div>
          </div>

          {/* Recent Projects */}
          {threads && threads.length > 0 && (
            <section className="px-6 pb-6">
              <div className="mx-auto max-w-6xl">
                <div className="flex items-center justify-between pb-3">
                  <h2 className="text-lg font-semibold">Recent Projects</h2>
                  <Link
                    href="/workspace/chats"
                    className="text-muted-foreground hover:text-foreground flex items-center gap-0.5 text-xs"
                  >
                    View All
                    <ChevronRightIcon className="size-3" />
                  </Link>
                </div>
                <ScrollArea className="w-full">
                  <div className="flex gap-4 pb-4">
                    {threads.slice(0, 8).map((thread) => (
                      <Link
                        key={thread.thread_id}
                        href={`/workspace/graphs/${thread.thread_id}`}
                        className="group flex w-40 shrink-0 flex-col overflow-hidden rounded-xl border bg-card transition-shadow hover:shadow-lg"
                      >
                        <div className="flex h-24 items-center justify-center bg-gradient-to-br from-primary/5 to-primary/15">
                          <BarChart3Icon className="text-primary/40 size-10" />
                        </div>
                        <div className="flex items-start justify-between p-3">
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-xs font-medium">
                              {titleOfThread(thread)}
                            </p>
                            {thread.updated_at && (
                              <p className="text-muted-foreground mt-0.5 text-[10px]">
                                {formatTimeAgo(thread.updated_at)}
                              </p>
                            )}
                          </div>
                          <button
                            className="text-muted-foreground hover:text-foreground shrink-0 opacity-0 transition group-hover:opacity-100"
                            onClick={(e) => e.preventDefault()}
                          >
                            <MoreVerticalIcon className="size-3.5" />
                          </button>
                        </div>
                      </Link>
                    ))}
                  </div>
                  <ScrollBar orientation="horizontal" />
                </ScrollArea>
              </div>
            </section>
          )}

          {/* Templates */}
          <section className="px-6 pb-12">
            <div className="mx-auto max-w-6xl">
              <h2 className="pb-3 text-lg font-semibold">Templates</h2>

              {/* Category Tabs */}
              <div className="flex flex-wrap gap-2 pb-4">
                {TEMPLATE_CATEGORIES.map((cat) => (
                  <button
                    key={cat}
                    className={cn(
                      "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                      activeCategory === cat
                        ? "border-foreground bg-foreground text-background"
                        : "border-border text-muted-foreground hover:border-foreground hover:text-foreground",
                    )}
                    onClick={() => setActiveCategory(cat)}
                  >
                    {cat}
                  </button>
                ))}
              </div>

              {/* Template Cards */}
              <ScrollArea className="w-full">
                <div className="flex gap-4 pb-4">
                  {filteredTemplates.map((template) => (
                    <TemplateCard
                      key={template.id}
                      template={template}
                      onClick={() => handleTemplateClick(template)}
                    />
                  ))}
                  {filteredTemplates.length === 0 && (
                    <div className="text-muted-foreground flex h-32 w-full items-center justify-center text-sm">
                      No templates in this category yet
                    </div>
                  )}
                </div>
                <ScrollBar orientation="horizontal" />
              </ScrollArea>
            </div>
          </section>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
