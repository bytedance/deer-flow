import { parse } from "best-effort-json-parser";

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

    // Handle streaming JSON content - find the complete JSON object
    if (raw.startsWith('{')) {
      let braceCount = 0;
      let jsonEnd = -1;
      
      for (let i = 0; i < raw.length; i++) {
        if (raw[i] === '{') braceCount++;
        if (raw[i] === '}') braceCount--;
        if (braceCount === 0) {
          jsonEnd = i;
          break;
        }
      }
      
      // If we found a complete JSON object, extract only that part
      if (jsonEnd !== -1) {
        raw = raw.substring(0, jsonEnd + 1);
      } else {
        // Incomplete JSON, return fallback
        return fallback;
      }
    }

    return parse(raw) as T;
  } catch (error) {
    // Silently return fallback for any parsing errors
    return fallback;
  }
}
