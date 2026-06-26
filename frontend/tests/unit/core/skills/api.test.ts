import { beforeEach, describe, expect, test, rs } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "/backend",
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import { enableSkill, loadSkills } from "@/core/skills/api";

const mockedFetch = rs.mocked(fetcher);

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText: status >= 400 ? "Bad Request" : "OK",
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  mockedFetch.mockReset();
});

describe("skills api", () => {
  test("loads skills from the gateway", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        skills: [
          {
            name: "data-analysis",
            description: "Analyze data",
            category: "public",
            license: "MIT",
            enabled: true,
          },
        ],
      }),
    );

    await expect(loadSkills()).resolves.toEqual([
      {
        name: "data-analysis",
        description: "Analyze data",
        category: "public",
        license: "MIT",
        enabled: true,
      },
    ]);
    expect(mockedFetch).toHaveBeenCalledWith("/backend/api/skills");
  });

  test("throws backend detail when loading skills fails", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(403, { detail: "Skills are disabled for this user" }),
    );

    await expect(loadSkills()).rejects.toThrow(
      "Skills are disabled for this user",
    );
  });

  test("updates a skill enabled flag", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { success: true, skill_name: "data-analysis" }),
    );

    await expect(enableSkill("data-analysis", false)).resolves.toMatchObject({
      success: true,
      skill_name: "data-analysis",
    });
    expect(mockedFetch).toHaveBeenCalledWith("/backend/api/skills/data-analysis", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        enabled: false,
      }),
    });
  });

  test("throws backend detail when updating a skill fails", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(403, { detail: "Skill toggle denied" }),
    );

    await expect(enableSkill("foo", false)).rejects.toThrow(
      "Skill toggle denied",
    );
  });
});
