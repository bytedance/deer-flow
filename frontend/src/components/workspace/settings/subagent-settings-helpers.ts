export type OptionalNameListMode = "all" | "none" | "selected";

export function optionalNameListToDraft(value: string[] | null): {
  mode: OptionalNameListMode;
  text: string;
} {
  if (value == null) return { mode: "all", text: "" };
  if (value.length === 0) return { mode: "none", text: "" };
  return { mode: "selected", text: value.join(", ") };
}

export function optionalNameListFromDraft(
  mode: OptionalNameListMode,
  text: string,
): string[] | null {
  if (mode === "all") return null;
  if (mode === "none") return [];
  const values = text
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  return Array.from(new Set(values));
}

export function positiveInteger(value: string): number | null {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

export function isValidManagedSubagentName(value: string): boolean {
  return /^[A-Za-z0-9-]+$/.test(value.trim());
}
