export const TOOL_PREVIEW_LIMIT = 12_000;
const MAX_NODES = TOOL_PREVIEW_LIMIT;
const MAX_DEPTH = 6;

// UTF-16 limits must not leave half of a surrogate pair in the visible prefix.
function textPrefix(text: string, length: number): string {
  let end = Math.min(text.length, Math.max(0, length));
  if (
    end > 0 &&
    end < text.length &&
    text.charCodeAt(end - 1) >= 0xd800 &&
    text.charCodeAt(end - 1) <= 0xdbff &&
    text.charCodeAt(end) >= 0xdc00 &&
    text.charCodeAt(end) <= 0xdfff
  )
    end--;
  return text.slice(0, end);
}

/** Serialize bounded previews with space reserved for complete JSON tokens. */
export function formatToolDetail(value: unknown): {
  text: string;
  truncated: boolean;
} {
  let truncated = false;
  let nodes = 0;
  let budgetCollapses = 0;
  let generatedMarkers = 0;
  const seen = new WeakSet<object>();
  const marker = (budgetCollapsed = false) => {
    truncated = true;
    generatedMarkers++;
    if (budgetCollapsed) budgetCollapses++;
    return JSON.stringify("…");
  };
  const quote = (text: string, budget: number): string => {
    // Bound the input before escaping; escaping can expand each character.
    const candidate = JSON.stringify(textPrefix(text, budget));
    if (text.length <= budget && candidate.length <= budget) return candidate;
    truncated = true;
    let low = 0;
    let high = Math.min(text.length, budget);
    while (low < high) {
      const middle = Math.ceil((low + high) / 2);
      if (JSON.stringify(textPrefix(text, middle) + "…").length <= budget)
        low = middle;
      else high = middle - 1;
    }
    const prefix = textPrefix(text, low);
    if (prefix === "") return marker(true);
    return JSON.stringify(prefix + "…");
  };
  const visit = (item: unknown, depth: number, budget: number): string => {
    if (++nodes > MAX_NODES || depth > MAX_DEPTH) return marker();
    if (typeof item === "string") return quote(item, budget);
    if (
      item === null ||
      typeof item === "boolean" ||
      typeof item === "number"
    ) {
      const token = JSON.stringify(item);
      return token.length <= budget ? token : marker(true);
    }
    if (typeof item === "bigint") return quote(item.toString(), budget);
    if (typeof item !== "object") return quote(typeof item, budget);
    if (seen.has(item)) return marker();
    const array = Array.isArray(item);
    const indent = "  ".repeat(depth + 1);
    const closing = "\n" + "  ".repeat(depth) + (array ? "]" : "}");
    const notice = array ? '"…"' : '"…": "…"';
    // Reserve the closing delimiter and a possible final truncation entry.
    const reserve = closing.length + 2 + indent.length + notice.length;
    if (budget < 1 + reserve) return marker(true);
    seen.add(item);
    let output = array ? "[" : "{";
    let count = 0;
    let hasEllipsis = false;
    let tailMarkerEnd: number | undefined;
    const append = (entry: string, generated: boolean) => {
      output += entry;
      // Remember a complete entry boundary, never a character-budget cut.
      // A real later value clears it so middle array indices stay intact.
      if (array && generated) tailMarkerEnd ??= output.length;
      else tailMarkerEnd = undefined;
    };
    for (const key in item) {
      if (!Object.prototype.hasOwnProperty.call(item, key)) continue;
      const prefix = (count ? ",\n" : "\n") + indent;
      const available = budget - output.length - prefix.length - reserve;
      // Never shorten a property name, including its JSON escape sequences.
      const encodedKey = array
        ? ""
        : key.length <= available
          ? JSON.stringify(key) + ": "
          : null;
      if (
        nodes >= MAX_NODES ||
        encodedKey === null ||
        available - encodedKey.length < 3
      ) {
        truncated = true;
        if (array || !hasEllipsis) append(prefix + notice, true);
        break;
      }
      const descriptor = Object.getOwnPropertyDescriptor(item, key);
      const previousBudgetCollapses = budgetCollapses;
      const previousGeneratedMarkers = generatedMarkers;
      const child =
        descriptor && "value" in descriptor
          ? visit(descriptor.value, depth + 1, available - encodedKey.length)
          : marker();
      // Only exhausted space ends the array. Cycles/accessors/depth limits must
      // not hide later siblings, and a literal ellipsis is ordinary data.
      if (
        array &&
        budgetCollapses > previousBudgetCollapses &&
        child === notice
      ) {
        append(prefix + notice, true);
        break;
      }
      append(
        prefix + encodedKey + child,
        generatedMarkers > previousGeneratedMarkers && child === notice,
      );
      count++;
      if (key === "…") hasEllipsis = true;
    }
    seen.delete(item);
    if (tailMarkerEnd !== undefined) output = output.slice(0, tailMarkerEnd);
    return output + (output.length === 1 ? (array ? "]" : "}") : closing);
  };
  // Preserve tool text verbatim: JSON.parse can round IDs, drop duplicate keys,
  // and change quoted strings. Structured values are already decoded by the SDK.
  if (typeof value === "string") {
    truncated = value.length > TOOL_PREVIEW_LIMIT;
    return {
      text: truncated ? textPrefix(value, TOOL_PREVIEW_LIMIT - 1) + "…" : value,
      truncated,
    };
  }
  const text = visit(value, 0, TOOL_PREVIEW_LIMIT);
  return { text, truncated };
}
