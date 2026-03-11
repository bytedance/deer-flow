"use client";

import type { Editor } from "@tiptap/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { uploadFiles } from "@/core/uploads/api";
import { cn } from "@/lib/utils";

import { CHART_TEMPLATES } from "../chart-templates";

interface SlashMenuItem {
  title: string;
  description: string;
  icon: React.ReactNode;
  category: "text" | "chart" | "block";
  command: (editor: Editor) => void;
}

const chartIcon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="3" y="12" width="4" height="9" rx="1" />
    <rect x="10" y="7" width="4" height="14" rx="1" />
    <rect x="17" y="3" width="4" height="18" rx="1" />
  </svg>
);

const pieIcon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M21.21 15.89A10 10 0 1 1 8 2.83" />
    <path d="M22 12A10 10 0 0 0 12 2v10z" />
  </svg>
);

const lineIcon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polyline points="22 12 18 8 13 13 8 8 2 14" />
    <line x1="2" y1="20" x2="22" y2="20" />
  </svg>
);

const scatterIcon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="7" cy="15" r="2" /><circle cx="12" cy="9" r="2" />
    <circle cx="17" cy="13" r="2" /><circle cx="9" cy="5" r="1.5" />
    <circle cx="16" cy="7" r="1.5" />
  </svg>
);

const radarIcon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polygon points="12 2 22 8.5 22 15.5 12 22 2 15.5 2 8.5" />
    <polygon points="12 6 18 10 18 14 12 18 6 14 6 10" opacity="0.4" />
  </svg>
);

const gaugeIcon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12" />
    <path d="M12 12l4-6" strokeWidth="2.5" />
  </svg>
);

const heatmapIcon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <rect x="2" y="2" width="6" height="6" rx="1" fill="currentColor" opacity="0.7" />
    <rect x="9" y="2" width="6" height="6" rx="1" fill="currentColor" opacity="0.3" />
    <rect x="16" y="2" width="6" height="6" rx="1" fill="currentColor" opacity="0.5" />
    <rect x="2" y="9" width="6" height="6" rx="1" fill="currentColor" opacity="0.4" />
    <rect x="9" y="9" width="6" height="6" rx="1" fill="currentColor" opacity="0.9" />
    <rect x="16" y="9" width="6" height="6" rx="1" fill="currentColor" opacity="0.2" />
    <rect x="2" y="16" width="6" height="6" rx="1" fill="currentColor" opacity="0.6" />
    <rect x="9" y="16" width="6" height="6" rx="1" fill="currentColor" opacity="0.3" />
    <rect x="16" y="16" width="6" height="6" rx="1" fill="currentColor" opacity="0.8" />
  </svg>
);

const treemapIcon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <rect x="2" y="2" width="12" height="10" rx="1" />
    <rect x="16" y="2" width="6" height="10" rx="1" />
    <rect x="2" y="14" width="8" height="8" rx="1" />
    <rect x="12" y="14" width="10" height="8" rx="1" />
  </svg>
);

const funnelIcon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M3 4h18l-3 5H6L3 4z" /><path d="M6 9h12l-2 5H8L6 9z" /><path d="M8 14h8l-2 5h-4l-2-5z" />
  </svg>
);

const sankeyIcon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M2 5h3c4 0 4 6 8 6h9" /><path d="M2 12h3c4 0 4 5 8 5h9" /><path d="M2 19h3c4 0 4-7 8-7h9" />
  </svg>
);

const networkIcon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="6" cy="6" r="3" /><circle cx="18" cy="6" r="3" /><circle cx="12" cy="18" r="3" />
    <line x1="8.5" y1="7.5" x2="10" y2="16" /><line x1="15.5" y1="7.5" x2="14" y2="16" />
    <line x1="9" y1="6" x2="15" y2="6" />
  </svg>
);

const candlestickIcon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <line x1="6" y1="2" x2="6" y2="22" /><rect x="4" y="6" width="4" height="8" />
    <line x1="14" y1="4" x2="14" y2="20" /><rect x="12" y="8" width="4" height="6" />
    <line x1="20" y1="3" x2="20" y2="18" /><rect x="18" y="7" width="4" height="5" />
  </svg>
);

const sunburstIcon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <circle cx="12" cy="12" r="3" /><circle cx="12" cy="12" r="6" /><circle cx="12" cy="12" r="9" />
    <line x1="12" y1="3" x2="12" y2="1" /><line x1="12" y1="23" x2="12" y2="21" />
    <line x1="3" y1="12" x2="1" y2="12" /><line x1="23" y1="12" x2="21" y2="12" />
  </svg>
);

const CHART_ICON_MAP: Record<string, React.ReactNode> = {
  line: lineIcon,
  area: lineIcon,
  bar: chartIcon,
  "bar-horizontal": chartIcon,
  "stacked-bar": chartIcon,
  pie: pieIcon,
  donut: pieIcon,
  scatter: scatterIcon,
  bubble: scatterIcon,
  radar: radarIcon,
  heatmap: heatmapIcon,
  treemap: treemapIcon,
  sunburst: sunburstIcon,
  funnel: funnelIcon,
  gauge: gaugeIcon,
  candlestick: candlestickIcon,
  boxplot: chartIcon,
  sankey: sankeyIcon,
  graph: networkIcon,
  parallel: lineIcon,
  themeRiver: lineIcon,
};

function generateId() {
  return Math.random().toString(36).substring(2, 15);
}

function buildSlashItems(): SlashMenuItem[] {
  const textItems: SlashMenuItem[] = [
    {
      title: "Heading 1",
      description: "Large section heading",
      icon: <span className="text-xs font-bold text-foreground">H1</span>,
      category: "text",
      command: (editor) => editor.chain().focus().toggleHeading({ level: 1 }).run(),
    },
    {
      title: "Heading 2",
      description: "Medium section heading",
      icon: <span className="text-xs font-bold text-foreground">H2</span>,
      category: "text",
      command: (editor) => editor.chain().focus().toggleHeading({ level: 2 }).run(),
    },
    {
      title: "Heading 3",
      description: "Small section heading",
      icon: <span className="text-xs font-bold text-foreground">H3</span>,
      category: "text",
      command: (editor) => editor.chain().focus().toggleHeading({ level: 3 }).run(),
    },
    {
      title: "Bullet List",
      description: "Create a simple bullet list",
      icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" />
          <circle cx="3" cy="6" r="1" fill="currentColor" /><circle cx="3" cy="12" r="1" fill="currentColor" /><circle cx="3" cy="18" r="1" fill="currentColor" />
        </svg>
      ),
      category: "text",
      command: (editor) => editor.chain().focus().toggleBulletList().run(),
    },
    {
      title: "Numbered List",
      description: "Create a numbered list",
      icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="10" y1="6" x2="21" y2="6" /><line x1="10" y1="12" x2="21" y2="12" /><line x1="10" y1="18" x2="21" y2="18" />
          <text x="1" y="8" fontSize="8" fill="currentColor" stroke="none">1</text>
          <text x="1" y="14" fontSize="8" fill="currentColor" stroke="none">2</text>
          <text x="1" y="20" fontSize="8" fill="currentColor" stroke="none">3</text>
        </svg>
      ),
      category: "text",
      command: (editor) => editor.chain().focus().toggleOrderedList().run(),
    },
    {
      title: "Quote",
      description: "Add a blockquote",
      icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M3 21c3 0 7-1 7-8V5c0-1.25-.756-2.017-2-2H4c-1.25 0-2 .75-2 1.972V11c0 1.25.75 2 2 2 1 0 1 0 1 1v1c0 1-1 2-2 2s-1 .008-1 1.031V21z" />
          <path d="M15 21c3 0 7-1 7-8V5c0-1.25-.757-2.017-2-2h-4c-1.25 0-2 .75-2 1.972V11c0 1.25.75 2 2 2h.75c0 2.25.25 4-2.75 4v3z" />
        </svg>
      ),
      category: "text",
      command: (editor) => editor.chain().focus().toggleBlockquote().run(),
    },
    {
      title: "Divider",
      description: "Horizontal rule separator",
      icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="2" y1="12" x2="22" y2="12" />
        </svg>
      ),
      category: "text",
      command: (editor) => editor.chain().focus().setHorizontalRule().run(),
    },
    {
      title: "Code Block",
      description: "Add a code snippet",
      icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="16 18 22 12 16 6" /><polyline points="8 6 2 12 8 18" />
        </svg>
      ),
      category: "text",
      command: (editor) => editor.chain().focus().toggleCodeBlock().run(),
    },
    {
      title: "Text",
      description: "Plain paragraph text",
      icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M4 7V4h16v3" /><line x1="12" y1="4" x2="12" y2="20" /><line x1="8" y1="20" x2="16" y2="20" />
        </svg>
      ),
      category: "text",
      command: (editor) => editor.chain().focus().setParagraph().run(),
    },
  ];

  const chartItems: SlashMenuItem[] = CHART_TEMPLATES.map((t) => ({
    title: t.label,
    description: t.description,
    icon: CHART_ICON_MAP[t.type] ?? chartIcon,
    category: "chart" as const,
    command: (editor: Editor) => {
      editor
        .chain()
        .focus()
        .insertContent({
          type: "chartNode",
          attrs: {
            chartId: generateId(),
            title: t.label,
            option: t.option,
          },
        })
        .run();
    },
  }));

  const blockItems: SlashMenuItem[] = [
    {
      title: "Narrative Card",
      description: "AI-generated summary card",
      icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14 2 14 8 20 8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
          <polyline points="10 9 9 9 8 9" />
        </svg>
      ),
      category: "block",
      command: (editor: Editor) => {
        editor
          .chain()
          .focus()
          .insertContent({
            type: "narrativeNode",
            attrs: { narrativeId: generateId(), title: "Executive Summary" },
            content: [
              {
                type: "paragraph",
                content: [{ type: "text", text: "Add your narrative summary here..." }],
              },
            ],
          })
          .run();
      },
    },
    {
      title: "Image",
      description: "Upload or embed an image",
      icon: (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
          <circle cx="8.5" cy="8.5" r="1.5" />
          <polyline points="21 15 16 10 5 21" />
        </svg>
      ),
      category: "block",
      command: () => {
        // Placeholder — overridden dynamically with threadId-aware version
      },
    },
  ];

  return [...textItems, ...blockItems, ...chartItems];
}

const ALL_ITEMS = buildSlashItems();

interface SlashCommandMenuProps {
  editor: Editor;
  threadId?: string;
}

export default function SlashCommandMenu({ editor, threadId }: SlashCommandMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const menuRef = useRef<HTMLDivElement>(null);
  const slashPosRef = useRef<number | null>(null);
  const selectedRef = useRef<HTMLButtonElement>(null);
  // Suppress handleUpdate during command execution
  const suppressRef = useRef(false);

  // Patch the Image command with the current threadId
  const items = useMemo(() => {
    return ALL_ITEMS.map((item) => {
      if (item.title === "Image") {
        return {
          ...item,
          command: (ed: Editor) => {
            const input = document.createElement("input");
            input.type = "file";
            input.accept = "image/*";
            input.onchange = () => {
              const file = input.files?.[0];
              if (!file) return;
              if (threadId) {
                void uploadFiles(threadId, [file]).then((response) => {
                  if (response.success && response.files.length > 0) {
                    const src = response.files[0]!.artifact_url;
                    ed.chain().focus().insertContent({ type: "image", attrs: { src } }).run();
                  }
                });
              } else {
                // Fallback: base64
                const reader = new FileReader();
                reader.onload = () => {
                  const src = reader.result as string;
                  ed.chain().focus().insertContent({ type: "image", attrs: { src } }).run();
                };
                reader.readAsDataURL(file);
              }
            };
            input.click();
          },
        };
      }
      return item;
    });
  }, [threadId]);

  const filteredItems = items.filter(
    (item) =>
      item.title.toLowerCase().includes(query.toLowerCase()) ||
      item.description.toLowerCase().includes(query.toLowerCase()) ||
      item.category.toLowerCase().includes(query.toLowerCase()),
  );

  const textItems = filteredItems.filter((i) => i.category === "text");
  const blockItems = filteredItems.filter((i) => i.category === "block");
  const chartItemsList = filteredItems.filter((i) => i.category === "chart");

  const executeCommand = useCallback(
    (index: number) => {
      const item = filteredItems[index];
      if (!item) return;

      // Capture range before any state changes
      const from = slashPosRef.current;
      const to = editor.state.selection.from;

      // Reset menu state
      setIsOpen(false);
      setQuery("");
      slashPosRef.current = null;

      // Suppress the handleUpdate listener so it doesn't interfere
      suppressRef.current = true;

      // Step 1: Delete the slash text
      if (from !== null) {
        editor.chain().focus().deleteRange({ from, to }).run();
      }

      // Step 2: Run the actual command (separate transaction, but handleUpdate is suppressed)
      item.command(editor);

      // Re-enable handler after current call stack completes
      queueMicrotask(() => {
        suppressRef.current = false;
      });
    },
    [editor, filteredItems],
  );

  useEffect(() => {
    setSelectedIndex(0);
  }, [query]);

  // Scroll selected item into view
  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  const handleKeyDownRef = useRef<(e: KeyboardEvent) => boolean>(() => false);
  handleKeyDownRef.current = (e: KeyboardEvent) => {
    if (!isOpen) return false;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((i) => (i + 1) % filteredItems.length);
      return true;
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((i) => (i - 1 + filteredItems.length) % filteredItems.length);
      return true;
    } else if (e.key === "Enter") {
      e.preventDefault();
      executeCommand(selectedIndex);
      return true;
    } else if (e.key === "Escape") {
      setIsOpen(false);
      setQuery("");
      slashPosRef.current = null;
      return true;
    }
    return false;
  };

  useEffect(() => {
    if (!editor) return;

    const domElement = editor.view.dom;
    const handler = (e: KeyboardEvent) => {
      if (handleKeyDownRef.current(e)) {
        e.stopPropagation();
      }
    };
    domElement.addEventListener("keydown", handler, { capture: true });
    return () => {
      domElement.removeEventListener("keydown", handler, { capture: true });
    };
  }, [editor]);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setIsOpen(false);
        setQuery("");
        slashPosRef.current = null;
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  useEffect(() => {
    if (!editor) return;

    const handleUpdate = () => {
      // Skip if we're in the middle of executing a command
      if (suppressRef.current) return;

      const { state } = editor;
      const { from } = state.selection;
      const textBefore = state.doc.textBetween(Math.max(0, from - 50), from, "\n");
      const slashMatch = /\/([^/\n]*)$/.exec(textBefore);

      if (slashMatch) {
        const matchStart = from - slashMatch[0].length;
        slashPosRef.current = matchStart;
        setQuery(slashMatch[1] ?? "");
        setIsOpen(true);

        const coords = editor.view.coordsAtPos(from);
        const editorRect = editor.view.dom.closest(".dashboard-editor")?.getBoundingClientRect();
        if (editorRect) {
          setPosition({
            top: coords.bottom - editorRect.top + 4,
            left: coords.left - editorRect.left,
          });
        }
      } else if (isOpen) {
        setIsOpen(false);
        setQuery("");
        slashPosRef.current = null;
      }
    };

    editor.on("update", handleUpdate);
    editor.on("selectionUpdate", handleUpdate);
    return () => {
      editor.off("update", handleUpdate);
      editor.off("selectionUpdate", handleUpdate);
    };
  }, [editor, isOpen]);

  if (!isOpen || filteredItems.length === 0) return null;

  let globalIndex = 0;

  return (
    <div
      ref={menuRef}
      className="absolute z-50 w-72 overflow-hidden rounded-xl border border-border bg-popover shadow-lg"
      style={{ top: position.top, left: position.left }}
    >
      <div className="max-h-80 overflow-y-auto p-1.5">
        {textItems.length > 0 && (
          <>
            <p className="px-3 pt-1.5 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Text & Formatting
            </p>
            {textItems.map((item) => {
              const idx = globalIndex++;
              return (
                <button
                  key={item.title}
                  ref={idx === selectedIndex ? selectedRef : undefined}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    executeCommand(idx);
                  }}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-lg px-3 py-1.5 text-left transition-colors",
                    idx === selectedIndex ? "bg-accent" : "hover:bg-accent/50",
                  )}
                >
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border bg-background text-muted-foreground">
                    {item.icon}
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground">{item.title}</p>
                    <p className="truncate text-xs text-muted-foreground">{item.description}</p>
                  </div>
                </button>
              );
            })}
          </>
        )}

        {blockItems.length > 0 && (
          <>
            <p className="mt-1 px-3 pt-1.5 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Blocks
            </p>
            {blockItems.map((item) => {
              const idx = globalIndex++;
              return (
                <button
                  key={item.title}
                  ref={idx === selectedIndex ? selectedRef : undefined}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    executeCommand(idx);
                  }}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-lg px-3 py-1.5 text-left transition-colors",
                    idx === selectedIndex ? "bg-accent" : "hover:bg-accent/50",
                  )}
                >
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border bg-background text-muted-foreground">
                    {item.icon}
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground">{item.title}</p>
                    <p className="truncate text-xs text-muted-foreground">{item.description}</p>
                  </div>
                </button>
              );
            })}
          </>
        )}

        {chartItemsList.length > 0 && (
          <>
            <p className="mt-1 px-3 pt-1.5 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Charts
            </p>
            {chartItemsList.map((item) => {
              const idx = globalIndex++;
              return (
                <button
                  key={item.title}
                  ref={idx === selectedIndex ? selectedRef : undefined}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    executeCommand(idx);
                  }}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-lg px-3 py-1.5 text-left transition-colors",
                    idx === selectedIndex ? "bg-accent" : "hover:bg-accent/50",
                  )}
                >
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-border bg-background text-muted-foreground">
                    {item.icon}
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-foreground">{item.title}</p>
                    <p className="truncate text-xs text-muted-foreground">{item.description}</p>
                  </div>
                </button>
              );
            })}
          </>
        )}
      </div>
    </div>
  );
}
