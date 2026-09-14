import { beforeEach, describe, expect, it, rs } from "@rstest/core";

const request = rs.hoisted(() => rs.fn());
rs.mock("@/core/api/fetcher", () => ({ fetch: request }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));

import {
  downloadSkillExport,
  loadSkillExportManifest,
  SkillExportRequestError,
} from "@/core/skills/export";

describe("custom skill export requests", () => {
  beforeEach(() => request.mockReset());
  it("binds download to the exact preview and forwards cancellation", async () => {
    request.mockResolvedValue(
      new Response("zip", { headers: { "content-type": "application/zip" } }),
    );
    const signal = new AbortController().signal;
    const blob = await downloadSkillExport("demo", "a".repeat(64), signal);
    expect(await blob.text()).toBe("zip");
    expect(request).toHaveBeenCalledWith(
      "/api/skills/custom/demo/export?expected_revision=" + "a".repeat(64),
      { signal, cache: "no-store" },
    );
  });
  it("surfaces a changed preview without retrying", async () => {
    request.mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: { code: "skill_changed", message: "Refresh preview" },
        }),
        { status: 409 },
      ),
    );
    await expect(
      downloadSkillExport("demo", "a".repeat(64), new AbortController().signal),
    ).rejects.toMatchObject({ status: 409, code: "skill_changed" });
    expect(request).toHaveBeenCalledTimes(1);
  });
  it("preserves safe server errors for preview", async () => {
    request.mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: { code: "skill_export_busy", message: "Busy" },
        }),
        { status: 429 },
      ),
    );
    await expect(
      loadSkillExportManifest("demo", new AbortController().signal),
    ).rejects.toBeInstanceOf(SkillExportRequestError);
  });
  it("does not hand an HTML response to the browser as a skill", async () => {
    request.mockResolvedValue(
      new Response("<html/>", { headers: { "content-type": "text/html" } }),
    );
    await expect(
      downloadSkillExport("demo", "a".repeat(64), new AbortController().signal),
    ).rejects.toThrow();
  });
});
