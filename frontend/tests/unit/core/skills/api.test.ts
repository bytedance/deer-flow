import { beforeEach, describe, expect, it, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "",
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import { installSkillFile, SkillRequestError } from "@/core/skills/api";

const mockedFetch = rs.mocked(fetcher);

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("installSkillFile", () => {
  it("posts the selected file as multipart form data", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        success: true,
        skill_name: "demo-skill",
        message: "installed",
      }),
    );
    const file = new File(["archive"], "demo.skill", {
      type: "application/octet-stream",
    });

    await expect(installSkillFile(file)).resolves.toMatchObject({
      skill_name: "demo-skill",
    });

    expect(mockedFetch).toHaveBeenCalledTimes(1);
    const [url, init] = mockedFetch.mock.calls[0]!;
    expect(url).toBe("/api/skills/install/upload");
    expect(init?.method).toBe("POST");
    expect(init?.headers).toBeUndefined();
    expect(init?.body).toBeInstanceOf(FormData);
    expect((init?.body as FormData).get("file")).toBe(file);
  });

  it("surfaces a string error detail", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(400, { detail: "Invalid .skill archive" }),
    );

    await expect(
      installSkillFile(new File(["bad"], "bad.skill")),
    ).rejects.toMatchObject({
      status: 400,
      message: "Invalid .skill archive",
    });
  });

  it("surfaces the message from a structured security error detail", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(400, {
        detail: {
          message: "Skill security scan failed",
          skill_name: "unsafe-skill",
          findings: [],
        },
      }),
    );

    await expect(
      installSkillFile(new File(["bad"], "unsafe.skill")),
    ).rejects.toMatchObject({
      status: 400,
      message: "Skill security scan failed",
    });
  });

  it("throws SkillRequestError for upload HTTP failures", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(409, { detail: "Skill already exists" }),
    );

    await expect(
      installSkillFile(new File(["duplicate"], "duplicate.skill")),
    ).rejects.toBeInstanceOf(SkillRequestError);
  });
});
