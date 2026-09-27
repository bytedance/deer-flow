import { beforeEach, describe, expect, rs, test } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "/backend",
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  formatSkillSecurityFindings,
  SkillRequestError,
  enableSkill,
  loadSkills,
  uploadSkillArchive,
} from "@/core/skills/api";

const mockedFetch = rs.mocked(fetcher);

function jsonResponse(
  status: number,
  body: unknown,
  statusText = status >= 400 ? "Error" : "OK",
): Response {
  return new Response(JSON.stringify(body), {
    status,
    statusText,
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

  test("preserves structured security findings for the upload UI", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(400, {
        detail: {
          message: "Static security scan blocked skill 'demo'",
          skill_name: "demo",
          findings: [
            {
              rule_id: "python-shell-exec",
              severity: "HIGH",
              file: "scripts/run.py",
              line: 7,
              message: "Python invokes a shell command.",
              remediation: "Remove the shell call.",
            },
          ],
        },
      }),
    );

    const error = await uploadSkillArchive(
      new File(["archive"], "demo.skill"),
    ).catch((caught: unknown) => caught);

    expect(error).toEqual(
      expect.objectContaining({
        name: "SkillRequestError",
        status: 400,
        skillName: "demo",
        findings: [
          expect.objectContaining({
            rule_id: "python-shell-exec",
            file: "scripts/run.py",
            line: 7,
          }),
        ],
      }),
    );
    if (!(error instanceof SkillRequestError)) {
      throw new Error("expected a SkillRequestError");
    }
    expect(formatSkillSecurityFindings(error.findings)).toBe(
      "HIGH python-shell-exec · scripts/run.py:7: Python invokes a shell command. Remove the shell call.",
    );
  });

  test("turns an unstructured proxy 413 into a typed request error", async () => {
    mockedFetch.mockResolvedValueOnce(
      new Response("", { status: 413, statusText: "" }),
    );

    await expect(
      uploadSkillArchive(new File(["archive"], "demo.skill")),
    ).rejects.toEqual(
      expect.objectContaining({
        name: "SkillRequestError",
        status: 413,
        message: "HTTP 413",
      }),
    );
  });

  test("limits formatted findings and reports how many remain", () => {
    const findings = Array.from({ length: 5 }, (_, index) => ({
      rule_id: `rule-${index + 1}`,
      severity: "HIGH",
      file: `scripts/run-${index + 1}.py`,
      line: index + 1,
      message: `Finding ${index + 1}.`,
      remediation: null,
    }));

    expect(formatSkillSecurityFindings(findings).split("\n")).toEqual([
      "HIGH rule-1 · scripts/run-1.py:1: Finding 1.",
      "HIGH rule-2 · scripts/run-2.py:2: Finding 2.",
      "HIGH rule-3 · scripts/run-3.py:3: Finding 3.",
      "... and 2 more",
    ]);
  });
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

  test("falls back to HTTP status when loading skills fails without detail", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(503, {}, ""));

    await expect(loadSkills()).rejects.toThrow("HTTP 503");
  });

  test("updates a skill enabled flag", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, { success: true, skill_name: "data-analysis" }),
    );

    await expect(enableSkill("data-analysis", false)).resolves.toMatchObject({
      success: true,
      skill_name: "data-analysis",
    });
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/skills/data-analysis",
      {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          enabled: false,
        }),
      },
    );
  });

  test("throws backend detail when updating a skill fails", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(403, { detail: "Skill toggle denied" }),
    );

    await expect(enableSkill("foo", false)).rejects.toThrow(
      "Skill toggle denied",
    );
  });

  test("falls back to HTTP status when updating a skill fails without detail", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(409, {}, ""));

    await expect(enableSkill("foo", false)).rejects.toThrow("HTTP 409");
  });
});
