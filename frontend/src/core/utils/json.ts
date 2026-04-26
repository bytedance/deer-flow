import { parse } from "best-effort-json-parser";

export function tryParseJSON(json: string) {
  try {
    const object = parse(json);
    return object;
  } catch {
    return undefined;
  }
}
