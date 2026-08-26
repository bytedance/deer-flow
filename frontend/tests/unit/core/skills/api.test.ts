import { beforeEach, describe, expect, rs, test } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "/backend",
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import { uploadSkillArchive } from "@/core/skills/api";

const mockedFetch = rs.mocked(fetcher);

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status >= 400 ? "Error" : "OK",
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("skills api", () => {
  test("uploads a local .skill archive as multipart form data", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        success: true,
        skill_name: "demo",
        message: "Installed demo",
      }),
    );
    const archive = new File(["archive"], "demo.skill", {
      type: "application/octet-stream",
    });

    await expect(uploadSkillArchive(archive)).resolves.toEqual({
      success: true,
      skill_name: "demo",
      message: "Installed demo",
    });

    expect(mockedFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockedFetch.mock.calls[0]!;
    expect(url).toBe("/backend/api/skills/install/upload");
    expect(init?.method).toBe("POST");
    expect(init?.headers).toBeUndefined();
    expect(init?.body).toBeInstanceOf(FormData);
    expect((init?.body as FormData).get("archive")).toBe(archive);
  });

  test("preserves the admin-required error contract", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(403, { detail: "Admin privileges required" }),
    );

    await expect(
      uploadSkillArchive(new File(["archive"], "demo.skill")),
    ).rejects.toEqual(
      expect.objectContaining({
        name: "SkillRequestError",
        status: 403,
      }),
    );
  });
});
