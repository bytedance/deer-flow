"use client";

import type { JSONContent } from "@tiptap/react";
import html2canvas from "html2canvas-pro";
import { jsPDF } from "jspdf";
import {
  BarChart3Icon,
  CheckIcon,
  ChevronDownIcon,
  ClockIcon,
  DownloadIcon,
  FileImageIcon,
  FileTextIcon,
  FilterIcon,
  ImageIcon,
  LayersIcon,
  LayoutDashboardIcon,
  Loader2Icon,
  PaletteIcon,
  PlayIcon,
  PlusIcon,
  RedoIcon,
  TypeIcon,
  UndoIcon,
  UserPlusIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { saveArtifact } from "@/core/artifacts/utils";
import { cn } from "@/lib/utils";

import { CHART_TEMPLATES } from "./chart-templates";
import { DASHBOARD_THEMES, setDashboardThemeId } from "./chart-themes";
import {
  clearDrillDown,
  getDrillDownFilter,
  subscribeDrillDown,
} from "./drill-down-events";
import DashboardEditorRaw, {
  type DashboardEditorHandle,
} from "./editor/dashboard-editor-raw";
import { PresentMode } from "./present-mode";

interface DatasetTable {
  title: string;
  headers: string[];
  rows: (string | number)[][];
}

function extractDatasets(content: JSONContent): DatasetTable[] {
  const tables: DatasetTable[] = [];
  if (!content?.content) return tables;

  for (const node of content.content) {
    if (node.type !== "chartNode" || !node.attrs?.option) continue;
    const opt = node.attrs.option as Record<string, unknown>;
    const chartTitle = (node.attrs.title as string) || "Chart Data";

    // Dataset-based charts
    const dataset = opt.dataset as { source?: unknown[][] } | undefined;
    if (dataset?.source && dataset.source.length > 0) {
      const headers = (dataset.source[0] as (string | number)[]).map(String);
      const rows = dataset.source.slice(1) as (string | number)[][];
      tables.push({ title: chartTitle, headers, rows });
      continue;
    }

    // Inline series[].data charts
    const series = opt.series;
    if (Array.isArray(series)) {
      for (const s of series) {
        const sr = s as Record<string, unknown>;
        const data = sr.data;
        if (!Array.isArray(data) || data.length === 0) continue;
        const sName = (sr.name as string) || chartTitle;
        const first = data[0];
        if (Array.isArray(first)) {
          // Array-of-arrays format
          tables.push({
            title: sName,
            headers: (first as unknown[]).map((_, i) => `Col ${i + 1}`),
            rows: data as (string | number)[][],
          });
        } else if (typeof first === "object" && first !== null) {
          // Array-of-objects format (pie chart { name, value })
          const obj = first as Record<string, unknown>;
          const keys = Object.keys(obj);
          tables.push({
            title: sName,
            headers: keys,
            rows: data.map((d) => keys.map((k) => (d as Record<string, unknown>)[k] as string | number)),
          });
        }
      }
    }
  }
  return tables;
}

function generateId() {
  return Math.random().toString(36).substring(2, 15);
}

type Tab = "text" | "media" | "graphs" | "theme";
type ViewMode = "preview" | "data" | "filters";

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: "text", label: "Text", icon: TypeIcon },
  { id: "media", label: "Media", icon: ImageIcon },
  { id: "graphs", label: "Graphs", icon: LayoutDashboardIcon },
  { id: "theme", label: "Theme", icon: PaletteIcon },
];

const VIEW_MODES: {
  id: ViewMode;
  label: string;
  icon: React.ElementType;
}[] = [
  { id: "preview", label: "Preview", icon: BarChart3Icon },
  { id: "data", label: "Data", icon: LayersIcon },
  { id: "filters", label: "Filters", icon: FilterIcon },
];

// Group chart templates by category
const CHART_CATEGORIES: { label: string; types: string[] }[] = [
  { label: "Basic", types: ["line", "area", "step-line", "bar", "bar-horizontal", "grouped-bar", "pie", "donut", "rose"] },
  { label: "Stacked & Mixed", types: ["stacked-bar", "stacked-area", "mixed-line-bar", "multi-axis", "negative-bar", "waterfall"] },
  { label: "Statistical", types: ["scatter", "bubble", "boxplot", "heatmap", "calendar-heatmap"] },
  { label: "Radial", types: ["radar", "polar-bar", "polar-line", "wind-rose", "gauge", "ringProgress"] },
  { label: "Hierarchical", types: ["treemap", "sunburst", "funnel"] },
  { label: "Relational", types: ["sankey", "graph", "parallel", "themeRiver"] },
  { label: "Financial", types: ["candlestick"] },
  { label: "Other", types: ["pictorial-bar", "progress-bar", "liquidfill", "timeline-bar", "slope", "dumbbell", "map-bubble"] },
];

interface DashboardPage {
  name: string;
  content: JSONContent;
  /** Original artifact filepath (e.g. /mnt/user-data/outputs/dashboard.json) for saving */
  filepath?: string;
}

interface GraphWorkspaceProps {
  className?: string;
  dashboardPages?: DashboardPage[];
  threadId?: string;
}

export function GraphWorkspace({
  className,
  dashboardPages = [],
  threadId,
}: GraphWorkspaceProps) {
  const [activeTab, setActiveTab] = useState<Tab>("graphs");
  const [viewMode, setViewMode] = useState<ViewMode>("preview");
  const [projectName, setProjectName] = useState("Untitled Project");
  const [themeId, setThemeId] = useState("default");
  const [themePopoverOpen, setThemePopoverOpen] = useState(false);
  const [graphsPopoverOpen, setGraphsPopoverOpen] = useState(false);
  const themeButtonRef = useRef<HTMLButtonElement>(null);
  const themePopoverRef = useRef<HTMLDivElement>(null);
  const graphsButtonRef = useRef<HTMLButtonElement>(null);
  const graphsPopoverRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<DashboardEditorHandle>(null);

  // Multi-page state
  const [pages, setPages] = useState<JSONContent[]>([]);
  const [activePage, setActivePage] = useState(0);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved">("idle");
  const [presenting, setPresenting] = useState(false);
  const [downloadMenuOpen, setDownloadMenuOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const downloadButtonRef = useRef<HTMLButtonElement>(null);
  const downloadMenuRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  // Debounced auto-save: saves editor content back to the artifact JSON file
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Store the active filepath in a ref so the debounced callback always sees current value
  const activeFilepathRef = useRef<string | undefined>(undefined);

  const handleEditorChange = useCallback(
    (updatedContent: JSONContent) => {
      const filepath = activeFilepathRef.current;
      if (!filepath || !threadId) return;

      // Clear existing timer
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);

      setSaveStatus("saving");
      saveTimerRef.current = setTimeout(() => {
        const jsonStr = JSON.stringify(updatedContent, null, 2);
        void saveArtifact({
          filepath,
          threadId,
          content: jsonStr,
        })
          .then(() => {
            setSaveStatus("saved");
            setTimeout(() => setSaveStatus("idle"), 2000);
          })
          .catch((err) => {
            console.error("Auto-save failed:", err);
            setSaveStatus("idle");
          });
      }, 1500); // 1.5s debounce
    },
    [threadId],
  );

  // Clean up save timer on unmount
  useEffect(() => {
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, []);

  // Sync theme to reactive store
  useEffect(() => {
    setDashboardThemeId(themeId);
  }, [themeId]);

  // Close popovers on outside click
  useEffect(() => {
    if (!themePopoverOpen && !graphsPopoverOpen && !downloadMenuOpen) return;
    const handler = (e: MouseEvent) => {
      if (
        themePopoverOpen &&
        themePopoverRef.current &&
        !themePopoverRef.current.contains(e.target as Node) &&
        themeButtonRef.current &&
        !themeButtonRef.current.contains(e.target as Node)
      ) {
        setThemePopoverOpen(false);
      }
      if (
        graphsPopoverOpen &&
        graphsPopoverRef.current &&
        !graphsPopoverRef.current.contains(e.target as Node) &&
        graphsButtonRef.current &&
        !graphsButtonRef.current.contains(e.target as Node)
      ) {
        setGraphsPopoverOpen(false);
      }
      if (
        downloadMenuOpen &&
        downloadMenuRef.current &&
        !downloadMenuRef.current.contains(e.target as Node) &&
        downloadButtonRef.current &&
        !downloadButtonRef.current.contains(e.target as Node)
      ) {
        setDownloadMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [themePopoverOpen, graphsPopoverOpen, downloadMenuOpen]);

  // Capture the content area as a canvas
  const captureContent = useCallback(async (): Promise<HTMLCanvasElement | null> => {
    const el = contentRef.current;
    if (!el) return null;
    // Temporarily expand the container so the full content is captured (not clipped by overflow)
    const prevOverflow = el.style.overflow;
    const prevHeight = el.style.height;
    const prevMaxHeight = el.style.maxHeight;
    el.style.overflow = "visible";
    el.style.height = "auto";
    el.style.maxHeight = "none";
    try {
      const canvas = await html2canvas(el, {
        backgroundColor: "#ffffff",
        scale: 2,
        useCORS: true,
        allowTaint: true,
        logging: false,
        // Capture the full scrollable content
        scrollX: 0,
        scrollY: 0,
        windowWidth: el.scrollWidth,
        windowHeight: el.scrollHeight,
      });
      return canvas;
    } finally {
      el.style.overflow = prevOverflow;
      el.style.height = prevHeight;
      el.style.maxHeight = prevMaxHeight;
    }
  }, []);

  const downloadAsPng = useCallback(async () => {
    setExporting(true);
    setDownloadMenuOpen(false);
    try {
      const canvas = await captureContent();
      if (!canvas) return;
      const dataUrl = canvas.toDataURL("image/png");
      const link = document.createElement("a");
      link.download = `${projectName || "dashboard"}.png`;
      link.href = dataUrl;
      link.click();
    } catch (err) {
      console.error("PNG export failed:", err);
    } finally {
      setExporting(false);
    }
  }, [captureContent, projectName]);

  const downloadAsPdf = useCallback(async () => {
    setExporting(true);
    setDownloadMenuOpen(false);
    try {
      const canvas = await captureContent();
      if (!canvas) return;
      const dataUrl = canvas.toDataURL("image/png");
      const imgWidth = canvas.width;
      const imgHeight = canvas.height;
      // Create PDF sized to content (A4 landscape width, scale height proportionally)
      const pdfWidth = 297; // A4 landscape width in mm
      const pdfHeight = (imgHeight / imgWidth) * pdfWidth;
      const pdf = new jsPDF({
        orientation: pdfHeight > pdfWidth ? "portrait" : "landscape",
        unit: "mm",
        format: [pdfWidth, pdfHeight],
      });
      pdf.addImage(dataUrl, "PNG", 0, 0, pdfWidth, pdfHeight);
      pdf.save(`${projectName || "dashboard"}.pdf`);
    } catch (err) {
      console.error("PDF export failed:", err);
    } finally {
      setExporting(false);
    }
  }, [captureContent, projectName]);

  // Sync dashboard pages from props with local pages
  const effectivePages = useMemo((): DashboardPage[] => {
    const makeUserPage = (content: JSONContent, i: number, offset: number): DashboardPage => ({
      name: `Page ${offset + i + 1}`,
      content,
      filepath: `/mnt/user-data/outputs/page-${offset + i + 1}.json`,
    });

    if (dashboardPages.length > 0) {
      return [
        ...dashboardPages,
        ...pages.map((content, i) => makeUserPage(content, i, dashboardPages.length)),
      ];
    }
    return pages.length > 0
      ? pages.map((content, i) => makeUserPage(content, i, 0))
      : [];
  }, [dashboardPages, pages]);

  const activeDashboardPage = effectivePages[activePage];
  const activeContent = activeDashboardPage?.content ?? null;
  const hasContent = !!activeContent;

  // Keep the filepath ref in sync for auto-save
  activeFilepathRef.current = activeDashboardPage?.filepath;

  // Subscribe to drill-down events
  const drillDownFilter = useSyncExternalStore(subscribeDrillDown, getDrillDownFilter, getDrillDownFilter);

  // Auto-switch to data view on drill-down
  useEffect(() => {
    if (drillDownFilter) {
      setViewMode("data");
    }
  }, [drillDownFilter]);

  const datasets = useMemo(
    () => (activeContent ? extractDatasets(activeContent) : []),
    [activeContent],
  );

  const addPage = useCallback(() => {
    setPages((prev) => [
      ...prev,
      { type: "doc", content: [{ type: "paragraph" }] },
    ]);
    setActivePage(effectivePages.length);
  }, [effectivePages.length]);

  const removePage = useCallback(
    (index: number) => {
      if (effectivePages.length <= 1) return;
      // Only allow removing user-added pages (after artifact pages)
      if (index < dashboardPages.length) return;
      const localIndex = index - dashboardPages.length;
      setPages((prev) => prev.filter((_, i) => i !== localIndex));
      setActivePage((prev) =>
        prev >= effectivePages.length - 1 ? Math.max(0, prev - 1) : prev,
      );
    },
    [dashboardPages.length, effectivePages.length],
  );

  const insertChart = useCallback(
    (templateType: string) => {
      const template = CHART_TEMPLATES.find((t) => t.type === templateType);
      if (!template) return;

      const editor = editorRef.current?.getEditor();
      if (editor) {
        editor
          .chain()
          .focus()
          .insertContent({
            type: "chartNode",
            attrs: {
              chartId: generateId(),
              title: template.label,
              option: template.option,
            },
          })
          .run();
        setGraphsPopoverOpen(false);
      }
    },
    [],
  );

  return (
    <div className={cn("flex h-full flex-col", className)}>
      {/* Outer padding wrapper */}
      <div
        className="flex h-full flex-col overflow-hidden rounded-2xl border m-4 ml-0 bg-white dark:bg-[oklch(0.24_0_0)]"
      >
        {/* Top Nav Bar */}
        <div className="flex h-[48px] shrink-0 items-center justify-between px-4">
          <div className="flex items-center gap-1">
            <button className="flex items-center gap-1.5 rounded-lg p-1.5 hover:bg-muted">
              <FileTextIcon className="size-4 text-red-500" />
              <ChevronDownIcon className="size-2.5 text-muted-foreground" />
            </button>
            <input
              className="max-w-[200px] rounded-lg bg-transparent px-2 py-1 text-sm font-medium outline-none hover:bg-muted focus:bg-muted"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
            />
            {saveStatus !== "idle" && (
              <span className="ml-1 text-[11px] text-muted-foreground">
                {saveStatus === "saving" ? "Saving..." : "Saved"}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button className="flex size-8 items-center justify-center rounded-xl text-muted-foreground hover:bg-muted hover:text-foreground">
              <ClockIcon className="size-[18px]" />
            </button>
            <div className="relative">
              <button
                ref={downloadButtonRef}
                onClick={() => setDownloadMenuOpen((prev) => !prev)}
                disabled={exporting}
                className="flex h-8 items-center gap-1.5 rounded-xl bg-blue-500/10 px-2.5 text-xs font-medium text-blue-600 hover:bg-blue-500/20 disabled:opacity-50 dark:text-blue-400"
              >
                {exporting ? (
                  <Loader2Icon className="size-4 animate-spin" />
                ) : (
                  <DownloadIcon className="size-4" />
                )}
                {exporting ? "Exporting..." : "Download"}
              </button>
              {downloadMenuOpen && (
                <div
                  ref={downloadMenuRef}
                  className="absolute right-0 z-50 mt-1.5 w-44 overflow-hidden rounded-xl border bg-popover shadow-lg"
                >
                  <button
                    onClick={() => void downloadAsPng()}
                    className="flex w-full items-center gap-2.5 px-3 py-2.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
                  >
                    <FileImageIcon className="size-4 text-green-500" />
                    Download as PNG
                  </button>
                  <div className="mx-3 h-px bg-border" />
                  <button
                    onClick={() => void downloadAsPdf()}
                    className="flex w-full items-center gap-2.5 px-3 py-2.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
                  >
                    <FileTextIcon className="size-4 text-red-500" />
                    Download as PDF
                  </button>
                </div>
              )}
            </div>
            <button
              onClick={() => effectivePages.length > 0 && setPresenting(true)}
              disabled={effectivePages.length === 0}
              className="flex h-8 items-center gap-1.5 rounded-xl bg-blue-500 px-3 text-xs font-medium text-white transition-colors hover:bg-blue-600 disabled:opacity-40"
            >
              <PlayIcon className="size-3.5 fill-current" />
              Present
            </button>
            <button className="flex h-8 items-center gap-1.5 rounded-xl bg-foreground px-2.5 text-xs font-medium text-background hover:opacity-90">
              <UserPlusIcon className="size-4" />
              Share
            </button>
          </div>
        </div>

        {/* Toolbar */}
        <div className="shrink-0 px-4 pb-4">
          <div className="relative flex h-12 w-full items-center rounded-full border bg-background px-3.5 shadow-[0px_2px_4px_0px_rgba(0,0,0,0.04)]">
            {/* Left: Undo / Redo + Fit */}
            <div className="flex items-center gap-1">
              <button className="flex size-7 items-center justify-center rounded-[10px] text-muted-foreground hover:bg-muted hover:text-foreground">
                <UndoIcon className="size-4" />
              </button>
              <button className="flex size-7 items-center justify-center rounded-[10px] text-muted-foreground hover:bg-muted hover:text-foreground">
                <RedoIcon className="size-4" />
              </button>
              <div className="mx-1.5 h-3 w-px bg-border" />
              <button className="flex h-7 items-center gap-1 rounded-full px-2 text-xs font-medium text-foreground hover:bg-muted">
                Fit
                <ChevronDownIcon className="size-3.5 text-muted-foreground" />
              </button>
            </div>

            {/* Center: Tabs */}
            <div className="absolute inset-0 flex items-center justify-center gap-3 pointer-events-none">
              {TABS.map((tab) => (
                <button
                  key={tab.id}
                  ref={
                    tab.id === "theme"
                      ? themeButtonRef
                      : tab.id === "graphs"
                        ? graphsButtonRef
                        : undefined
                  }
                  className={cn(
                    "pointer-events-auto flex w-[60px] flex-col items-center gap-0.5 rounded-[14px] px-1.5 pb-1 pt-1.5 transition-colors",
                    (tab.id === "theme" && themePopoverOpen) ||
                      (tab.id === "graphs" && graphsPopoverOpen)
                      ? "text-foreground"
                      : activeTab === tab.id
                        ? "text-foreground"
                        : "text-muted-foreground/50 hover:text-muted-foreground",
                  )}
                  onClick={() => {
                    if (tab.id === "theme") {
                      setThemePopoverOpen((prev) => !prev);
                      setGraphsPopoverOpen(false);
                    } else if (tab.id === "graphs") {
                      setGraphsPopoverOpen((prev) => !prev);
                      setThemePopoverOpen(false);
                    } else {
                      setActiveTab(tab.id);
                      setThemePopoverOpen(false);
                      setGraphsPopoverOpen(false);
                    }
                  }}
                >
                  <tab.icon className="size-3.5" />
                  <span className="text-[11px] leading-4 tracking-[0.33px]">
                    {tab.label}
                  </span>
                </button>
              ))}
            </div>
          </div>

          {/* Theme Popover */}
          {themePopoverOpen && (
            <div
              ref={themePopoverRef}
              className="absolute right-1/2 z-50 mt-2 w-[320px] translate-x-1/2 rounded-xl border bg-popover p-3 shadow-lg"
            >
              <p className="mb-2 text-xs font-semibold text-muted-foreground">
                Choose Theme
              </p>
              <div className="grid grid-cols-3 gap-2">
                {DASHBOARD_THEMES.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => {
                      setThemeId(t.id);
                      setThemePopoverOpen(false);
                    }}
                    className={cn(
                      "relative flex flex-col items-start gap-1.5 rounded-lg border p-2 transition-all hover:shadow-sm",
                      themeId === t.id
                        ? "border-primary bg-primary/5"
                        : "border-border hover:border-muted-foreground/30",
                    )}
                  >
                    {themeId === t.id && (
                      <CheckIcon className="absolute top-1.5 right-1.5 size-3 text-primary" />
                    )}
                    <div className="flex gap-1">
                      {t.preview.map((color, i) => (
                        <div
                          key={i}
                          className="size-4 rounded-full"
                          style={{ backgroundColor: color }}
                        />
                      ))}
                    </div>
                    <span className="text-[11px] font-medium text-foreground">
                      {t.name}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Graphs Gallery Popover */}
          {graphsPopoverOpen && (
            <div
              ref={graphsPopoverRef}
              className="absolute right-1/2 z-50 mt-2 w-[480px] max-h-[420px] translate-x-1/2 overflow-y-auto rounded-xl border bg-popover p-4 shadow-lg"
            >
              <p className="mb-3 text-xs font-semibold text-muted-foreground">
                Insert Chart
              </p>
              {CHART_CATEGORIES.map((cat) => {
                const templates = cat.types
                  .map((type) => CHART_TEMPLATES.find((t) => t.type === type))
                  .filter(Boolean);
                if (templates.length === 0) return null;
                return (
                  <div key={cat.label} className="mb-3">
                    <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                      {cat.label}
                    </p>
                    <div className="grid grid-cols-4 gap-1.5">
                      {templates.map((t) => (
                        <button
                          key={t!.type}
                          onClick={() => insertChart(t!.type)}
                          className="flex flex-col items-center gap-1 rounded-lg border border-transparent p-2 text-center transition-colors hover:border-border hover:bg-muted/50"
                        >
                          <div className="flex size-8 items-center justify-center rounded-md bg-muted/60 text-muted-foreground">
                            <BarChart3Icon className="size-3.5" />
                          </div>
                          <span className="text-[10px] font-medium leading-tight text-foreground/80">
                            {t!.label}
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Segmented Control: Preview / Data / Filters */}
        <div className="shrink-0 px-4 pb-4">
          <div className="inline-flex items-center gap-1 rounded-xl bg-muted/70 p-[3px]">
            {VIEW_MODES.map((mode) => (
              <button
                key={mode.id}
                className={cn(
                  "flex h-[26px] items-center gap-1 rounded-[10px] px-2.5 text-xs font-medium transition-all",
                  viewMode === mode.id
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground/50 hover:text-muted-foreground",
                )}
                onClick={() => setViewMode(mode.id)}
              >
                <mode.icon className="size-3.5" />
                {mode.label}
              </button>
            ))}
          </div>
        </div>

        {/* Content Area */}
        <div ref={contentRef} className="min-h-0 flex-1 overflow-auto">
          {viewMode === "preview" && (
            <div className="mx-auto max-w-[1033px] px-6 pb-6">
              {hasContent ? (
                <DashboardEditorRaw
                  ref={editorRef}
                  key={activePage}
                  content={activeContent}
                  threadId={threadId}
                  onContentChange={handleEditorChange}
                />
              ) : effectivePages.length > 0 ? (
                <DashboardEditorRaw
                  ref={editorRef}
                  key={activePage}
                  content={{ type: "doc", content: [{ type: "paragraph" }] }}
                  threadId={threadId}
                  onContentChange={handleEditorChange}
                />
              ) : (
                <DashboardEditorRaw
                  ref={editorRef}
                  key="empty"
                  content={{ type: "doc", content: [{ type: "paragraph" }] }}
                  threadId={threadId}
                  onContentChange={handleEditorChange}
                />
              )}
            </div>
          )}

          {viewMode === "data" && (
            <div className="mx-auto max-w-[1033px] space-y-6 px-6 pb-6">
              {drillDownFilter && (
                <div className="flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-4 py-2.5 dark:border-blue-800 dark:bg-blue-950/30">
                  <FilterIcon className="size-4 text-blue-500" />
                  <p className="flex-1 text-xs text-blue-700 dark:text-blue-300">
                    Filtered by <span className="font-semibold">{drillDownFilter.chartTitle}</span>
                    {drillDownFilter.dimensionValue && (
                      <> &mdash; {String(drillDownFilter.dimensionName)}: <span className="font-semibold">{String(drillDownFilter.dimensionValue)}</span></>
                    )}
                  </p>
                  <button
                    onClick={() => clearDrillDown()}
                    className="rounded-md px-2 py-1 text-[11px] font-medium text-blue-600 hover:bg-blue-100 dark:text-blue-400 dark:hover:bg-blue-900/30"
                  >
                    Clear filter
                  </button>
                </div>
              )}
              {datasets.length > 0 ? (
                datasets.map((dataset, i) => (
                  <div key={i} className="overflow-hidden rounded-xl border">
                    <div className="border-b bg-muted/30 px-4 py-3">
                      <h3 className="text-sm font-medium">{dataset.title}</h3>
                      <p className="text-xs text-muted-foreground">
                        {dataset.rows.length} rows
                      </p>
                    </div>
                    <div className="overflow-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b bg-muted/20">
                            {dataset.headers.map((h, j) => (
                              <th
                                key={j}
                                className="px-4 py-2.5 text-left font-medium text-muted-foreground"
                              >
                                {h}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {dataset.rows.map((row, ri) => {
                            const isHighlighted = dataset.title === drillDownFilter?.chartTitle
                              && ri === drillDownFilter?.dataIndex;
                            return (
                            <tr
                              key={ri}
                              className={cn(
                                "border-b last:border-0",
                                isHighlighted
                                  ? "bg-blue-50 dark:bg-blue-950/30"
                                  : "hover:bg-muted/10",
                              )}
                            >
                              {row.map((cell, ci) => (
                                <td key={ci} className="px-4 py-2">
                                  {String(cell)}
                                </td>
                              ))}
                            </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ))
              ) : (
                <div className="flex h-64 items-center justify-center rounded-xl border border-dashed text-muted-foreground">
                  <p className="text-sm">No data available yet</p>
                </div>
              )}
            </div>
          )}

          {viewMode === "filters" && (
            <div className="mx-auto max-w-[1033px] px-6 pb-6">
              <div className="flex h-64 items-center justify-center rounded-xl border border-dashed text-muted-foreground">
                <p className="text-sm">Filters will be available here</p>
              </div>
            </div>
          )}
        </div>

        {/* Page Tabs Bar */}
        {effectivePages.length > 0 && (
          <div className="flex h-9 shrink-0 items-center gap-px border-t bg-muted/30 px-2">
            {effectivePages.map((page, i) => (
              <button
                key={i}
                onClick={() => setActivePage(i)}
                className={cn(
                  "group/tab flex h-7 items-center gap-1.5 rounded-lg px-3 text-xs font-medium transition-colors",
                  activePage === i
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {page.name}
                {effectivePages.length > 1 && i >= dashboardPages.length && (
                  <span
                    onClick={(e) => {
                      e.stopPropagation();
                      removePage(i);
                    }}
                    className={cn(
                      "flex size-4 items-center justify-center rounded transition-opacity",
                      activePage === i
                        ? "opacity-60 hover:opacity-100"
                        : "opacity-0 group-hover/tab:opacity-60 group-hover/tab:hover:opacity-100",
                    )}
                  >
                    <XIcon className="size-3" />
                  </span>
                )}
              </button>
            ))}
            <button
              onClick={addPage}
              className="flex size-7 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-background hover:text-foreground"
            >
              <PlusIcon className="size-3.5" />
            </button>
          </div>
        )}
      </div>

      {/* Present Mode Overlay */}
      {presenting && effectivePages.length > 0 && (
        <PresentMode
          slides={effectivePages}
          startIndex={activePage}
          threadId={threadId}
          onExit={() => setPresenting(false)}
        />
      )}
    </div>
  );
}
