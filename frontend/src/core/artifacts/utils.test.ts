import { describe, expect, test } from "vitest";

import { resolveArtifactURL, urlOfArtifact } from "./utils";

describe("artifact URL helpers", () => {
  test("keeps virtual artifact paths unchanged", () => {
    expect(
      urlOfArtifact({
        filepath: "/mnt/user-data/outputs/widget.vsfx",
        threadId: "thread-123",
      }),
    ).toBe("/api/threads/thread-123/artifacts/mnt/user-data/outputs/widget.vsfx");
  });

  test("normalizes host-side thread output paths into virtual artifact URLs", () => {
    const hostPath =
      "/Users/zhou/Code/deer-flow/backend/.deer-flow/threads/thread-123/user-data/outputs/factory_122x45x8_retry.vsfx";

    expect(
      urlOfArtifact({
        filepath: hostPath,
        threadId: "thread-123",
      }),
    ).toBe(
      "/api/threads/thread-123/artifacts/mnt/user-data/outputs/factory_122x45x8_retry.vsfx",
    );
  });

  test("normalizes host-side paths for download URLs too", () => {
    const hostPath =
      "/Users/zhou/Code/deer-flow/backend/.deer-flow/threads/thread-123/user-data/outputs/nested/factory.properties.json";

    expect(
      urlOfArtifact({
        download: true,
        filepath: hostPath,
        threadId: "thread-123",
      }),
    ).toBe(
      "/api/threads/thread-123/artifacts/mnt/user-data/outputs/nested/factory.properties.json?download=true",
    );
  });

  test("resolveArtifactURL also normalizes host-side thread output paths", () => {
    const hostPath =
      "/Users/zhou/Code/deer-flow/backend/.deer-flow/threads/thread-123/user-data/outputs/factory_122x45x8_retry.vsfx";

    expect(resolveArtifactURL(hostPath, "thread-123")).toBe(
      "/api/threads/thread-123/artifacts/mnt/user-data/outputs/factory_122x45x8_retry.vsfx",
    );
  });
});
