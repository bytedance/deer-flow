import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "@rstest/core";

const browserViewRoot = join(
  import.meta.dirname,
  "../../../../../src/components/workspace/browser-view",
);

describe("browser stream transport", () => {
  it("requests binary frames and does not decode binary messages as JSON", () => {
    const apiSource = readFileSync(join(browserViewRoot, "api.ts"), "utf8");
    const hookSource = readFileSync(
      join(browserViewRoot, "use-browser-stream.ts"),
      "utf8",
    );

    expect(apiSource).toContain('query.set("frame_format", "binary")');
    expect(hookSource).toContain('socket.binaryType = "blob"');
    expect(hookSource).toContain("useSyncExternalStore");
    expect(hookSource).toContain("frameBuffer.push");
    expect(hookSource).not.toContain("await message.data.text()");
  });
});
