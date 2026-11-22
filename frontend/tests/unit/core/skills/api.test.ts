import { beforeEach, describe, expect, rs, test } from "@rstest/core";

rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "/backend",
}));

import { fetch as fetcher } from "@/core/api/fetcher";
import {
  deleteCustomSkill,
  enableSkill,
  formatSkillSecurityFindings,
  inspectSkillSource,
  installSkillSource,
  loadCustomSkill,
  loadSkills,
  SkillRequestError,
  updateCustomSkill,
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
  test("retains a typed HTTP failure when the response body is JSON null", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(403, null));
    await expect(enableSkill("demo", true)).rejects.toMatchObject({
      name: "SkillRequestError",
      status: 403,
      message: "HTTP 403: Error",
    });
  });

  test("keeps upload soft failures when the response body is JSON null", async () => {
    mockedFetch.mockResolvedValueOnce(jsonResponse(500, null));
    await expect(
      uploadSkillArchive(new File(["archive"], "demo.skill")),
    ).resolves.toEqual({
      success: false,
      skill_name: "",
      message: "HTTP 500: Error",
      enabled: false,
    });
  });
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

  test("preserves the permission-denied error contract", async () => {
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
      jsonResponse(200, { name: "data-analysis", enabled: false }),
    );

    await expect(enableSkill("data-analysis", false)).resolves.toMatchObject({
      name: "data-analysis",
      enabled: false,
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

  test("normalizes legacy string errors to a null code", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(403, { detail: "Permission denied" }),
    );
    const error = await enableSkill("demo", true).catch(
      (caught: unknown) => caught,
    );
    expect(error).toMatchObject({ code: null, retryAfter: null });
  });

  test("inspects a source through the CSRF-capable fetch wrapper", async () => {
    const preview = {
      source: "vercel-labs/skills@find-skills",
      source_url: "https://skills.sh/vercel-labs/skills/find-skills",
      skill_name: "find-skills",
      description: "Find skills",
      snapshot_digest: "a".repeat(64),
      upstream_hash: null,
      file_count: 1,
      total_bytes: 42,
    };
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, preview));

    await expect(inspectSkillSource(preview.source)).resolves.toEqual(preview);
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/skills/install/source/inspect",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: preview.source }),
        signal: undefined,
      },
    );
  });

  test("returns structured source codes, findings, and Retry-After", async () => {
    mockedFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          detail: {
            code: "skill_source_rate_limited",
            message: "Slow down",
          },
        }),
        { status: 429, headers: { "Retry-After": "17" } },
      ),
    );
    await expect(inspectSkillSource("owner/repo@skill")).rejects.toMatchObject({
      name: "SkillRequestError",
      code: "skill_source_rate_limited",
      retryAfter: "17",
      findings: [],
    });

    mockedFetch.mockResolvedValueOnce(
      jsonResponse(400, {
        detail: {
          code: "skill_security_scan_failed",
          message: "Blocked",
          findings: [
            {
              rule_id: "shell",
              severity: "HIGH",
              file: "SKILL.md",
              line: 3,
              message: "Shell execution",
              remediation: null,
            },
          ],
        },
      }),
    );
    await expect(
      installSkillSource({
        source: "owner/repo@skill",
        expected_snapshot_digest: "a".repeat(64),
      }),
    ).rejects.toMatchObject({
      code: "skill_security_scan_failed",
      findings: [expect.objectContaining({ rule_id: "shell" })],
    });
  });

  test("installs the exact inspected snapshot digest", async () => {
    mockedFetch.mockResolvedValueOnce(
      jsonResponse(200, {
        success: true,
        skill_name: "demo",
        message: "Installed",
      }),
    );
    const request = {
      source: "owner/repo@demo",
      expected_snapshot_digest: "b".repeat(64),
    };
    await installSkillSource(request);
    expect(mockedFetch).toHaveBeenCalledWith(
      "/backend/api/skills/install/source",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
        signal: undefined,
      },
    );
  });

  test("loads, edits, and deletes encoded custom skill paths", async () => {
    const skill = {
      name: "my skill",
      description: "Demo",
      category: "custom",
      license: "",
      enabled: true,
      editable: true,
      content: "---\nname: demo\n---\n",
    };
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, skill));
    await expect(loadCustomSkill("my skill")).resolves.toEqual(skill);
    expect(mockedFetch).toHaveBeenLastCalledWith(
      "/backend/api/skills/custom/my%20skill",
      { signal: undefined, cache: "no-store" },
    );

    mockedFetch.mockResolvedValueOnce(jsonResponse(200, skill));
    await updateCustomSkill("my skill", skill.content);
    expect(mockedFetch).toHaveBeenLastCalledWith(
      "/backend/api/skills/custom/my%20skill",
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: skill.content }),
      },
    );

    mockedFetch.mockResolvedValueOnce(jsonResponse(200, { success: true }));
    await expect(deleteCustomSkill("my skill")).resolves.toEqual({
      success: true,
    });
    expect(mockedFetch).toHaveBeenLastCalledWith(
      "/backend/api/skills/custom/my%20skill",
      { method: "DELETE" },
    );
  });
});
