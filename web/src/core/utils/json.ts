import { parse } from "best-effort-json-parser";

/**
 * Extract valid JSON from content that may have extra tokens.
 * Finds the last closing brace/bracket that could be valid JSON.
 */
function extractValidJSON(content: string): string {
  let braceCount = 0;
  let bracketCount = 0;
  let inString = false;
  let escapeNext = false;
  let lastValidEnd = -1;

  for (let i = 0; i < content.length; i++) {
    const char = content[i];
    
    if (escapeNext) {
      escapeNext = false;
      continue;
    }
    
    if (char === "\\") {
      escapeNext = true;
      continue;
    }
    
    if (char === '"' && !escapeNext) {
      inString = !inString;
      continue;
    }
    
    if (inString) {
      continue;
    }
    
    if (char === "{") {
      braceCount++;
    } else if (char === "}") {
      braceCount--;
      if (braceCount === 0) {
        lastValidEnd = i;
      }
    } else if (char === "[") {
      bracketCount++;
    } else if (char === "]") {
      bracketCount--;
      if (bracketCount === 0) {
        lastValidEnd = i;
      }
    }
  }
  
  if (lastValidEnd > 0) {
    return content.substring(0, lastValidEnd + 1);
  }
  
  return content;
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
    
    // First attempt: try to extract valid JSON to remove extra tokens
    if (raw.startsWith("{") || raw.startsWith("[")) {
      raw = extractValidJSON(raw);
    }
    
    // Parse the cleaned content
    return parse(raw) as T;
  } catch {
    // Fallback: try to extract meaningful content from malformed JSON
    // This is a last-resort attempt to salvage partial data
    return fallback;
  }
}
