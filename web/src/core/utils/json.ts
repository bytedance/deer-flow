import { parse } from "best-effort-json-parser";

/**
 * Extract the first balanced JSON value from the provided content.
 * This avoids returning trailing tokens that cause the best-effort parser
 * to emit console errors (and trigger Next.js overlays in dev mode).
 */
function extractFirstJSONValue(content: string): string {
  const trimmed = content.trimStart();
  if (trimmed.length === 0) {
    return trimmed;
  }

  // Ensure we start from the first structural character ({ or [)
  const firstStructuralIndex = trimmed.search(/[\[{]/);
  const candidate = firstStructuralIndex > 0
    ? trimmed.slice(firstStructuralIndex)
    : trimmed;

  const stack: Array<"}" | "]"> = [];
  let inString = false;
  let escapeNext = false;

  for (let i = 0; i < candidate.length; i++) {
    const char = candidate[i];

    if (inString) {
      if (escapeNext) {
        escapeNext = false;
        continue;
      }

      if (char === "\\") {
        escapeNext = true;
        continue;
      }

      if (char === "\"") {
        inString = false;
      }
      continue;
    }

    if (char === "\"") {
      inString = true;
      continue;
    }

    if (char === "{" || char === "[") {
      stack.push(char === "{" ? "}" : "]");
      continue;
    }

    if (char === "}" || char === "]") {
      const expected = stack.pop();
      if (!expected || expected !== char) {
        return candidate.slice(0, i + 1);
      }

      if (stack.length === 0) {
        return candidate.slice(0, i + 1);
      }
    }
  }

  return candidate;
}

export function parseJSON<T>(json: string | null | undefined, fallback: T) {
  if (!json) {
    return fallback;
  }
  try {
    let raw = json
      .trim()
      .replace(/^```json\s*/, "")
      .replace(/^```js\s*/, "")
      .replace(/^```ts\s*/, "")
      .replace(/^```plaintext\s*/, "")
      .replace(/^```\s*/, "")
      .replace(/\s*```$/, "");

    raw = raw.trim();
    if (!raw) {
      return fallback;
    }

    const firstChar = raw[0];
    const isJSONObject = firstChar === "{";
    const isJSONArray = firstChar === "[";
    const isJSONString = firstChar === "\"";

    if (!isJSONObject && !isJSONArray && !isJSONString) {
      return fallback;
    }

    // First attempt: try to extract valid JSON to remove extra tokens.
    if (isJSONObject || isJSONArray) {
      raw = extractFirstJSONValue(raw);
    }

    // Parse the cleaned content
    return parse(raw) as T;
  } catch {
    // Fallback: try to extract meaningful content from malformed JSON
    // This is a last-resort attempt to salvage partial data
    return fallback;
  }
}
