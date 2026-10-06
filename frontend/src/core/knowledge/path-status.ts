/**
 * P3 per-path sub-status assembly (spec 2026-08-11 §5): turns the document's
 * `path_status` into hover-breakdown lines. Pure — the tooltip component in
 * document-panel stays a thin renderer over these lines.
 */
import type { KnowledgeDocument } from "./types";

export interface PathStatusLine {
  path: "asr" | "segment" | "caption" | "vector" | "graph" | "wiki";
  /** Raw state string (vector/graph/wiki/video-leg enums differ — see types.ts). */
  state: string;
  /**
   * Set only for the graph leg mid-indexing: `progress_percent` is
   * graph-sourced (settled/total chunks), so the hover combines them as
   * 「图谱 索引中 87%」instead of duplicating the number elsewhere.
   */
  percent?: number;
}

/**
 * Assembly rule; returns null for legacy rows (`path_status` null) so the
 * caller renders no hover at all (spec §5 兼容契约).
 */
export function pathStatusLines(
  doc: Pick<KnowledgeDocument, "path_status" | "progress_percent" | "status">,
): PathStatusLine[] | null {
  const status = doc.path_status;
  if (!status) {
    return null;
  }
  const indexingGraph =
    doc.status === "indexing" && status.graph === "indexing";
  // Prep legs (spec 2026-09-08 §5; the text caption leg joined 2026-09-23 D8): asr/segment/
  // caption sit upstream of the retrieval legs, so they lead the breakdown. Presence is the
  // whole rule — a leg shows when the payload carries its key (video documents write the
  // three video legs, a text document with images writes its own caption verdict).
  const videoLegs: PathStatusLine[] = (["asr", "segment", "caption"] as const)
    .filter((leg) => status[leg] !== undefined)
    .map((leg) => ({ path: leg, state: status[leg]! }));
  return [
    ...videoLegs,
    { path: "vector", state: status.vector },
    {
      path: "graph",
      state: status.graph,
      ...(indexingGraph ? { percent: doc.progress_percent } : {}),
    },
    { path: "wiki", state: status.wiki },
  ];
}
