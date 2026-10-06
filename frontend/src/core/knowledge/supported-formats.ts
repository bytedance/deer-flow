/**
 * Upload allowlist helpers (phase-2 batch-1 Task 6, spec §6). The backend
 * `GET /api/knowledge-bases/supported-formats` endpoint is the source of
 * truth; the fallback constant mirrors it so the client-side guard still
 * works before the query resolves (or if the endpoint is unreachable).
 */
export const FALLBACK_SUPPORTED_SUFFIXES: readonly string[] = [
  ".md",
  ".markdown",
  ".txt",
  ".csv",
  // Spreadsheet suffixes (spec 2026-09-09 §8): mirror the backend's rag.table-gated
  // union. The `/supported-formats` endpoint is the source of truth (it returns these
  // only when `rag.table.enabled` is on); this fallback is the optimistic
  // pre-resolution client guard, so it lists them unconditionally.
  ".tsv",
  ".xlsx",
  ".xls",
  ".pdf",
  ".doc",
  ".docx",
  ".ppt",
  ".pptx",
  ".png",
  ".jpg",
  ".jpeg",
];

/** Lowercase dotted suffix, `Path.suffix` parity (dotfiles have no suffix). */
export function fileSuffix(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot <= 0 ? "" : name.slice(dot).toLowerCase();
}

/** Split files into allowlisted/rejected by suffix, preserving order. */
export function partitionFilesBySuffix<T extends { name: string }>(
  files: readonly T[],
  suffixes: readonly string[],
): { accepted: T[]; rejected: T[] } {
  const allowed = new Set(suffixes.map((s) => s.toLowerCase()));
  const accepted: T[] = [];
  const rejected: T[] = [];
  for (const file of files) {
    (allowed.has(fileSuffix(file.name)) ? accepted : rejected).push(file);
  }
  return { accepted, rejected };
}

/** File-picker `accept` attribute: sorted, comma-separated dotted suffixes. */
export function acceptAttribute(suffixes: readonly string[]): string {
  return [...suffixes].sort().join(",");
}
