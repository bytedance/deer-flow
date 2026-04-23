const DEFAULT_PATH = "/workspace";

export function sanitizePostLoginPath(raw: string | null | undefined): string {
  if (!raw || typeof raw !== "string") return DEFAULT_PATH;
  const t = raw.trim();
  if (!t.startsWith("/") || t.startsWith("//")) return DEFAULT_PATH;
  return t;
}
