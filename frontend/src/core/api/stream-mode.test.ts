import { describe, expect, it } from "vitest";

import { sanitizeRunStreamOptions } from "./stream-mode";

describe("sanitizeRunStreamOptions", () => {
  it("drops unsupported stream modes", () => {
    const result = sanitizeRunStreamOptions({
      streamMode: ["values", "tools", "messages-tuple"],
    });

    expect(result?.streamMode).toEqual(["values", "messages-tuple"]);
  });

  it("falls back to values when all modes are unsupported", () => {
    const result = sanitizeRunStreamOptions({
      streamMode: ["tools", "events"],
    });

    expect(result?.streamMode).toEqual(["values"]);
  });
});
