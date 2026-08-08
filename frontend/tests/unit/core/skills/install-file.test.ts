import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({ fetch: rs.fn() }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));

import { fetch as fetcher } from "@/core/api/fetcher";
import { installSkillFile } from "@/core/skills/api";

const fetchMock = rs.mocked(fetcher);

describe("installSkillFile", () => {
  beforeEach(() => {
    fetchMock.mockReset();
  });

  it("uploads and installs an offline skill package", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          success: true,
          skill_name: "demo",
          message: "Installed demo",
        }),
        { status: 200 },
      ),
    );

    const result = await installSkillFile(new File(["package"], "demo.skill"));

    expect(result).toMatchObject({ success: true, skill_name: "demo" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/skills/install/upload");
    const body = fetchMock.mock.calls[0]?.[1]?.body;
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get("file")).toBeInstanceOf(File);
  });

  it("surfaces installation failures", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Invalid skill package" }), {
        status: 400,
      }),
    );

    await expect(
      installSkillFile(new File(["package"], "bad.skill")),
    ).rejects.toMatchObject({ status: 400, message: "Invalid skill package" });
  });

  it("surfaces structured security scan failures", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          detail: { message: "Security scan blocked this package" },
        }),
        { status: 400 },
      ),
    );

    await expect(
      installSkillFile(new File(["package"], "unsafe.skill")),
    ).rejects.toMatchObject({
      status: 400,
      message: "Security scan blocked this package",
    });
  });
});
