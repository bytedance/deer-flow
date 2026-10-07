/**
 * P3 per-path sub-status assembly (spec 2026-08-11 §5): turns the document's
 * `path_status` into hover-breakdown lines. Pure — the tooltip component in
 * document-panel stays a thin renderer over these lines.
 */
import type { KnowledgeDocument } from "./types";

export interface PathStatusLine {
  path: "vector" | "caption";
  /** Raw state string (the vector and caption leg enums differ — see types.ts). */
  state: string;
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
  // The caption leg (image descriptions feeding the vector leg) is written
  // only by documents with images; a settled string state is the whole rule.
  const lines: PathStatusLine[] = [];
  if (typeof status.caption === "string") {
    lines.push({ path: "caption", state: status.caption });
  }
  lines.push({ path: "vector", state: status.vector });
  return lines;
}
