import { describe, expect, it } from "@rstest/core";

import { resolveStaticDemoArtifact } from "@/core/threads/static-demo";

describe("resolveStaticDemoArtifact", () => {
  const threadId = "7cfa5f8f-a2f8-47ad-acbd-da7137baf990";

  it("resolves a manifest-owned artifact", () => {
    expect(
      resolveStaticDemoArtifact(threadId, [
        "mnt",
        "user-data",
        "outputs",
        "index.html",
      ]),
    ).toBe(`/demo/threads/${threadId}/user-data/outputs/index.html`);
  });

  it.each([
    ["unknown", ["mnt", "user-data", "outputs", "index.html"]],
    [threadId, ["mnt", "user-data", "outputs", "missing.txt"]],
    [threadId, ["mnt", "user-data", "outputs", "..", "thread.json"]],
    [threadId, ["mnt", "user-data", "outputs", "%2e%2e", "thread.json"]],
    [threadId, ["mnt", "user-data", "outputs%2F..%2Fthread.json"]],
  ])("rejects an unknown or unsafe path", (candidateThreadId, segments) => {
    expect(resolveStaticDemoArtifact(candidateThreadId, segments)).toBeNull();
  });
});
