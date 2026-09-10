export const TOOL_PREVIEW_LIMIT = 12_000;
const MAX_NODES = TOOL_PREVIEW_LIMIT;
const MAX_DEPTH = 6;

/** Serialize bounded previews with space reserved for complete JSON tokens. */
export function formatToolDetail(value: unknown): {
  text: string;
  truncated: boolean;
} {
  let truncated = false;
  let nodes = 0;
  let truncations = 0;
  const seen = new WeakSet<object>();
  const marker = () => {
    truncated = true;
    truncations++;
    return JSON.stringify("…");
  };
  const quote = (text: string, budget: number): string => {
    // Bound the input before escaping; escaping can expand each character.
    const candidate = JSON.stringify(text.slice(0, budget));
    if (text.length <= budget && candidate.length <= budget) return candidate;
    truncated = true;
    truncations++;
    let low = 0;
    let high = Math.min(text.length, budget);
    while (low < high) {
      const middle = Math.ceil((low + high) / 2);
      if (JSON.stringify(text.slice(0, middle) + "…").length <= budget)
        low = middle;
      else high = middle - 1;
    }
    return JSON.stringify(text.slice(0, low) + "…");
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
      return token.length <= budget ? token : marker();
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
    if (budget < 1 + reserve) return marker();
    seen.add(item);
    let output = array ? "[" : "{";
    let count = 0;
    let hasEllipsis = false;
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
        truncations++;
        if (array || !hasEllipsis) output += prefix + notice;
        break;
      }
      const descriptor = Object.getOwnPropertyDescriptor(item, key);
      const previousTruncations = truncations;
      const child =
        descriptor && "value" in descriptor
          ? visit(descriptor.value, depth + 1, available - encodedKey.length)
          : marker();
      // A generated marker ends the array preview; literal ellipsis values do not.
      // Count new truncations because an earlier sibling may already be truncated.
      if (array && truncations > previousTruncations && child === notice) {
        output += prefix + notice;
        break;
      }
      output += prefix + encodedKey + child;
      count++;
      if (key === "…") hasEllipsis = true;
    }
    seen.delete(item);
    return output + (output.length === 1 ? (array ? "]" : "}") : closing);
  };
  // 只尝试解析有界的文本，长结果直接展示文本前缀。
  let source = value;
  if (
    typeof value === "string" &&
    value.length <= TOOL_PREVIEW_LIMIT &&
    value !== ""
  ) {
    try {
      source = JSON.parse(value) as unknown;
    } catch {
      /* 普通文本保持原样。 */
    }
  }
  if (typeof source === "string") {
    truncated = source.length > TOOL_PREVIEW_LIMIT;
    return {
      text: truncated ? source.slice(0, TOOL_PREVIEW_LIMIT - 1) + "…" : source,
      truncated,
    };
  }
  const text = visit(source, 0, TOOL_PREVIEW_LIMIT);
  return { text, truncated };
}
