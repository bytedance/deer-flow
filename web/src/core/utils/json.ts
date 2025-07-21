export function parseJSON<T>(json: string | null | undefined, fallback: T): T {
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

    // Early return for empty or invalid content
    if (!raw || raw.length === 0) {
      return fallback;
    }

    // For streaming content, try to extract complete JSON
    if (raw.startsWith("{")) {
      // Find the matching closing brace
      let braceCount = 0;
      let jsonEnd = -1;
      let inString = false;
      let escapeNext = false;

      for (let i = 0; i < raw.length; i++) {
        const char = raw[i];

        if (escapeNext) {
          escapeNext = false;
          continue;
        }

        if (char === "\\") {
          escapeNext = true;
          continue;
        }

        if (char === '"') {
          inString = !inString;
          continue;
        }

        if (!inString) {
          if (char === "{") braceCount++;
          if (char === "}") braceCount--;
          if (braceCount === 0) {
            jsonEnd = i;
            break;
          }
        }
      }

      // If we found a complete JSON object, extract only that part
      if (jsonEnd !== -1) {
        raw = raw.substring(0, jsonEnd + 1);
      } else {
        // Incomplete JSON during streaming, return fallback
        return fallback;
      }
    }

    // Validate that it looks like valid JSON before parsing
    if (!raw.startsWith("{") && !raw.startsWith("[")) {
      return fallback;
    }

    // Use native JSON.parse only
    const result = JSON.parse(raw);
    return result as T;
  } catch (error) {
    // For any parsing errors, silently return fallback
    // This prevents console errors during streaming
    return fallback;
  }
}
