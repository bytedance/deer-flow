"use client";

import { type NodeViewProps, NodeViewContent, NodeViewWrapper } from "@tiptap/react";
import { FileTextIcon, LoaderIcon, RefreshCwIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

import { getAPIClient } from "@/core/api";
import { cn } from "@/lib/utils";

import { getDashboardTheme, subscribeDashboardTheme } from "../chart-themes";

function useTheme() {
  return useSyncExternalStore(subscribeDashboardTheme, getDashboardTheme, getDashboardTheme);
}

const PLACEHOLDER_TEXT = "Add your narrative summary here...";

/**
 * Extract a text summary of all dashboard content surrounding this node
 * so the AI can generate a meaningful executive summary.
 */
function extractDashboardContext(editor: NodeViewProps["editor"]): string {
  const parts: string[] = [];

  editor.state.doc.descendants((node) => {
    if (node.type.name === "chartNode") {
      const title = node.attrs.title as string;
      const opt = node.attrs.option as Record<string, unknown> | undefined;
      parts.push(`Chart: "${title}"`);

      // Extract dataset headers + first few rows
      const dataset = opt?.dataset as { source?: unknown[][] } | undefined;
      if (dataset?.source && dataset.source.length > 0) {
        const header = dataset.source[0] as string[];
        parts.push(`  Columns: ${header.join(", ")}`);
        const preview = dataset.source.slice(1, 4).map((r) => (r as string[]).join(", "));
        parts.push(`  Sample data: ${preview.join(" | ")}`);
      }

      // Extract inline series data info
      const series = opt?.series;
      if (Array.isArray(series)) {
        for (const s of series) {
          const sr = s as Record<string, unknown>;
          const name = sr.name as string | undefined;
          const data = sr.data;
          if (name) parts.push(`  Series: "${name}"`);
          if (Array.isArray(data)) parts.push(`  Data points: ${data.length}`);
        }
      }
    }

    if (node.type.name === "metricNode") {
      const label = node.attrs.label as string;
      const value = node.attrs.value as string;
      parts.push(`Metric: ${label} = ${value}`);
    }

    if (node.type.name === "heading" || node.type.name === "paragraph") {
      const text = node.textContent.trim();
      if (text && text !== PLACEHOLDER_TEXT) {
        parts.push(`Text: "${text.slice(0, 200)}"`);
      }
    }
  });

  return parts.join("\n");
}

export function NarrativeNodeView({ node, selected, editor, getPos }: NodeViewProps) {
  const { title } = node.attrs;
  const [hovered, setHovered] = useState(false);
  const [generating, setGenerating] = useState(false);
  const hasGenerated = useRef(false);
  const theme = useTheme();
  const accent = theme.colors[0] ?? "#2563eb";

  const generateSummary = useCallback(async () => {
    if (generating) return;
    setGenerating(true);

    try {
      const context = extractDashboardContext(editor);
      if (!context.trim()) {
        setGenerating(false);
        return;
      }

      const client = getAPIClient();
      const thread = await client.threads.create();

      const result = await client.runs.wait(thread.thread_id, "lead_agent", {
        input: {
          messages: [
            {
              role: "user",
              content: `[NARRATIVE SUMMARY REQUEST — Text only, no tools, no files]
You are writing a concise executive summary for a data dashboard. Write 2-4 sentences that highlight key insights, trends, and notable findings from the data below.

Write in a professional, analytical tone. Use specific numbers where available. Do NOT use markdown headers or bullet points — just flowing prose paragraphs.

Dashboard contents:
${context}

Write the executive summary now (plain text, 2-4 sentences):`,
            },
          ],
        },
        config: { configurable: { thread_id: thread.thread_id } },
      });

      // Extract the last AI message
      const messages = (result as Record<string, unknown>)?.messages;
      if (Array.isArray(messages)) {
        for (let i = messages.length - 1; i >= 0; i--) {
          const msg = messages[i] as Record<string, unknown>;
          if (msg?.type === "ai" || msg?.role === "assistant") {
            let content = typeof msg.content === "string" ? msg.content : "";
            if (!content) continue;

            // Strip any markdown fences or leading/trailing whitespace
            content = content.replace(/```[\s\S]*?```/g, "").trim();
            // Remove any leading "Executive Summary:" or similar headers
            content = content.replace(/^(executive\s+summary[:\s]*)/i, "").trim();

            if (content) {
              // Replace the placeholder content inside this node
              const pos = typeof getPos === "function" ? getPos() : undefined;
              if (pos != null) {
                const nodeAt = editor.state.doc.nodeAt(pos);
                if (nodeAt) {
                  // Replace all content inside the narrativeNode
                  const from = pos + 1; // start of content
                  const to = pos + nodeAt.nodeSize - 1; // end of content
                  editor
                    .chain()
                    .focus()
                    .insertContentAt(
                      { from, to },
                      content.split("\n\n").map((para) => ({
                        type: "paragraph",
                        content: para.trim() ? [{ type: "text", text: para.trim() }] : [],
                      })),
                    )
                    .run();
                }
              }
              break;
            }
          }
        }
      }
    } catch (err) {
      console.error("Narrative generation failed:", err);
    } finally {
      setGenerating(false);
    }
  }, [editor, generating, getPos]);

  // Auto-generate on mount if content is the placeholder
  useEffect(() => {
    if (hasGenerated.current) return;
    // Check if the node content is just the placeholder text
    const pos = typeof getPos === "function" ? getPos() : undefined;
    if (pos == null) return;
    const nodeAt = editor.state.doc.nodeAt(pos);
    if (!nodeAt) return;
    const textContent = nodeAt.textContent.trim();
    if (textContent === PLACEHOLDER_TEXT || textContent === "") {
      hasGenerated.current = true;
      void generateSummary();
    }
  }, [editor, getPos, generateSummary]);

  return (
    <NodeViewWrapper>
      <div
        className="group relative"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
      >
        {/* Drag handle */}
        {editor.isEditable && (
          <div
            data-drag-handle
            draggable="true"
            className={cn(
              "absolute -left-8 top-1/2 z-10 -translate-y-1/2 cursor-grab rounded-md p-1 text-muted-foreground transition-opacity hover:bg-muted hover:text-foreground active:cursor-grabbing",
              hovered || selected ? "opacity-100" : "opacity-0",
            )}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <circle cx="9" cy="5" r="1.5" />
              <circle cx="15" cy="5" r="1.5" />
              <circle cx="9" cy="12" r="1.5" />
              <circle cx="15" cy="12" r="1.5" />
              <circle cx="9" cy="19" r="1.5" />
              <circle cx="15" cy="19" r="1.5" />
            </svg>
          </div>
        )}

        <div
          className={cn(
            "relative my-3 overflow-hidden rounded-xl border transition-all duration-200",
            selected
              ? "border-primary/40 shadow-[0_0_0_3px_rgba(37,99,235,0.1)]"
              : "border-border/50 shadow-[0_1px_3px_0px_rgba(0,0,0,0.03)]",
          )}
          style={{ background: "linear-gradient(180deg, #ffffff 0%, #fafafa 100%)" }}
        >
          {/* Accent top bar */}
          <div
            className="absolute inset-x-0 top-0 h-[2px]"
            style={{
              background: `linear-gradient(90deg, ${accent}, ${accent}40)`,
            }}
          />

          {/* Header */}
          <div className="flex items-center justify-between px-5 pt-4 pb-2">
            <div className="flex items-center gap-2">
              <div
                className="flex size-6 items-center justify-center rounded-md"
                style={{ backgroundColor: accent + "15", color: accent }}
              >
                <FileTextIcon className="size-3.5" />
              </div>
              <p className="text-[13px] font-semibold tracking-[-0.01em] text-foreground/90">
                {title as string}
              </p>
            </div>
            {editor.isEditable && (hovered || selected || generating) && (
              <button
                onClick={() => void generateSummary()}
                disabled={generating}
                className={cn(
                  "flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-medium transition-colors",
                  generating
                    ? "text-muted-foreground cursor-not-allowed"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                {generating ? (
                  <LoaderIcon className="size-3 animate-spin" />
                ) : (
                  <RefreshCwIcon className="size-3" />
                )}
                {generating ? "Generating..." : "Regenerate"}
              </button>
            )}
          </div>

          {/* Generating indicator */}
          {generating && (
            <div className="mx-5 mb-2 flex items-center gap-2 rounded-lg bg-muted/50 px-3 py-2">
              <LoaderIcon className="size-3.5 animate-spin text-muted-foreground" />
              <span className="text-xs text-muted-foreground">Generating summary from dashboard data...</span>
            </div>
          )}

          {/* Editable content area */}
          <div className="px-5 pb-4">
            <NodeViewContent className="narrative-content text-sm leading-relaxed text-foreground/80" />
          </div>
        </div>
      </div>
    </NodeViewWrapper>
  );
}
