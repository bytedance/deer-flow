/**
 * Document error productization (2026-08-30): the raw ``doc.error`` the
 * worker persists is an English exception string ("retry limit reached (5
 * attempts)…"). Users never see it — known patterns map to a friendly kind
 * rendered through i18n copy (``tk.docErrors[kind]``); the raw text no
 * longer appears anywhere in the UI (not even as a hover title).
 */
export type DocErrorKind =
  | "empty"
  | "unsupported"
  | "retryLimit"
  | "serviceUnconfigured"
  | "timeout"
  | "indexIncomplete"
  | "noIndexableContent"
  | "unknown";

/** Pattern-ordered classification; case-insensitive substring match. */
export function classifyDocError(error: string | null | undefined): DocErrorKind {
  const text = (error ?? "").toLowerCase();
  // 索引完整性=终态结论文（RFC §5.2 表行 4，worker 最后追加）：与既有腿标记
  // （如 caption 降级串里的 "timeout"）共存时终态原因赢——它才是 failed 的直接解释。
  if (text.includes("向量索引不完整")) return "indexIncomplete";
  if (text.includes("无可索引内容")) return "noIndexableContent";
  if (text.includes("file is empty")) return "empty";
  if (text.includes("unsupported file type")) return "unsupported";
  if (text.includes("retry limit reached")) return "retryLimit";
  if (text.includes("mineru_api_token")) return "serviceUnconfigured";
  if (text.includes("timed out") || text.includes("timeout")) return "timeout";
  return "unknown";
}
