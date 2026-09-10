export const TOOL_PREVIEW_LIMIT = 12_000;
const MAX_NODES = TOOL_PREVIEW_LIMIT;
const MAX_DEPTH = 6;

/** 先限制遍历和字符串长度，再序列化；不对完整载荷执行 stringify。 */
export function formatToolDetail(value: unknown): {
  text: string;
  truncated: boolean;
} {
  let truncated = false;
  let remaining = TOOL_PREVIEW_LIMIT;
  let nodes = 0;
  const seen = new WeakSet<object>();
  const cutString = (text: string) => {
    const cut = text.slice(0, Math.max(0, remaining));
    remaining -= cut.length;
    if (cut.length < text.length) {
      truncated = true;
      return cut.length > 0 ? cut.slice(0, -1) + "…" : "…";
    }
    return cut;
  };
  const visit = (item: unknown, depth: number): unknown => {
    if (++nodes > MAX_NODES || remaining <= 0 || depth > MAX_DEPTH) {
      truncated = true;
      return "…";
    }
    if (typeof item === "string") return cutString(item);
    if (item === null || typeof item === "boolean" || typeof item === "number")
      return item;
    if (typeof item === "bigint") return item.toString();
    if (typeof item !== "object") return typeof item;
    if (seen.has(item)) {
      truncated = true;
      return "…";
    }
    seen.add(item);
    const output: unknown[] | Record<string, unknown> = Array.isArray(item)
      ? []
      : (Object.create(null) as Record<string, unknown>);
    // 不创建完整的 keys/entries 数组，达到预算即停止读取子值。
    for (const key in item) {
      if (!Object.prototype.hasOwnProperty.call(item, key)) continue;
      // 对象键必须完整保留，截短后可能与已有键重名并覆盖真实数据。
      const keyLength = Array.isArray(output) ? 0 : key.length;
      if (nodes >= MAX_NODES || remaining <= 0 || keyLength > remaining) {
        truncated = true;
        if (Array.isArray(output)) output.push("…");
        else if (!("…" in output)) output["…"] = "…";
        break;
      }
      remaining -= keyLength;
      const descriptor = Object.getOwnPropertyDescriptor(item, key);
      const child =
        descriptor && "value" in descriptor
          ? visit(descriptor.value, depth + 1)
          : "…";
      if (!descriptor || !("value" in descriptor)) truncated = true;
      if (Array.isArray(output)) output.push(child);
      else output[key] = child;
    }
    seen.delete(item);
    return output;
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
  const bounded = visit(source, 0);
  const serialized =
    typeof bounded === "string" ? bounded : JSON.stringify(bounded, null, 2);
  if (serialized.length > TOOL_PREVIEW_LIMIT) truncated = true;
  return {
    text:
      serialized.length > TOOL_PREVIEW_LIMIT
        ? serialized.slice(0, TOOL_PREVIEW_LIMIT - 1) + "…"
        : serialized,
    truncated,
  };
}
