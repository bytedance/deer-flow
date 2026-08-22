import { beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient } from "@tanstack/react-query";

rs.mock("@/core/skills/api", () => ({
  enableSkill: rs.fn(),
  installSkillFile: rs.fn(),
  SkillRequestError: class SkillRequestError extends Error {},
}));

import { installSkillFile } from "@/core/skills/api";
import { getInstallSkillFileMutationOptions } from "@/core/skills/hooks";

const mockedInstallSkillFile = rs.mocked(installSkillFile);

beforeEach(() => {
  mockedInstallSkillFile.mockReset();
});

describe("skill file install mutation", () => {
  it("invalidates the skills query after a successful install", async () => {
    mockedInstallSkillFile.mockResolvedValue({
      success: true,
      skill_name: "demo-skill",
      message: "installed",
    });
    const client = new QueryClient();
    const invalidateQueries = rs
      .spyOn(client, "invalidateQueries")
      .mockResolvedValue();
    const mutation = client
      .getMutationCache()
      .build(client, getInstallSkillFileMutationOptions(client));
    const file = new File(["archive"], "demo.skill");

    await mutation.execute(file);

    expect(mockedInstallSkillFile.mock.calls[0]?.[0]).toBe(file);
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["skills"] });
  });
});
