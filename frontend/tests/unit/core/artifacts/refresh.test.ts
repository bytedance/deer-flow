import { describe, expect, test } from "@rstest/core";

import { hasActiveWriteForArtifact } from "@/core/artifacts/refresh";

const ARTIFACT_PATH = "/mnt/user-data/outputs/report.md";

function writeCall({
  id = "call-1",
  name = "write_file",
  path = ARTIFACT_PATH,
}: {
  id?: string;
  name?: string;
  path?: string;
} = {}) {
  return {
    type: "ai",
    tool_calls: [{ id, name, args: { path } }],
  };
}

describe("artifact refresh targeting", () => {
  test("detects an unresolved write for the selected artifact", () => {
    expect(hasActiveWriteForArtifact([writeCall()], ARTIFACT_PATH)).toBe(true);
    expect(
      hasActiveWriteForArtifact(
        [writeCall({ name: "str_replace" })],
        ARTIFACT_PATH,
      ),
    ).toBe(true);
  });

  test("ignores completed, unrelated, and non-write tool calls", () => {
    expect(
      hasActiveWriteForArtifact(
        [writeCall(), { type: "tool", tool_call_id: "call-1", content: "OK" }],
        ARTIFACT_PATH,
      ),
    ).toBe(false);
    expect(
      hasActiveWriteForArtifact(
        [writeCall({ path: "/mnt/user-data/outputs/other.md" })],
        ARTIFACT_PATH,
      ),
    ).toBe(false);
    expect(
      hasActiveWriteForArtifact(
        [writeCall({ name: "read_file" })],
        ARTIFACT_PATH,
      ),
    ).toBe(false);
  });
});
