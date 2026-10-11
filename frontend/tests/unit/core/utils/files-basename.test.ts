import { describe, expect, it } from "@rstest/core";

import { checkCodeFile, getFileExtension } from "@/core/utils/files";

describe("file type detection from the basename", () => {
  it.each([
    ["/mnt/user-data/outputs/Dockerfile", "dockerfile"],
    ["/mnt/user-data/outputs/Makefile", "makefile"],
    ["/mnt/user-data/outputs/project.v1/Dockerfile", "dockerfile"],
    ["/mnt/user-data/outputs/project.v1/Makefile", "makefile"],
    ["Dockerfile", "dockerfile"],
    ["Makefile", "makefile"],
    ["/mnt/user-data/outputs/project.v1/main.PY", "python"],
    ["/mnt/user-data/outputs/project.v1/.gitignore", "git-commit"],
    ["/mnt/user-data/outputs/project.v1/.env", "dotenv"],
    ["/mnt/user-data/outputs/project.v1/report%20final.py", "python"],
  ])("recognizes %s as %s", (filepath, language) => {
    expect(checkCodeFile(filepath)).toEqual({ isCodeFile: true, language });
  });

  it("does not infer a type from a dotted parent directory", () => {
    const filepath = "/mnt/user-data/outputs/main.py/unknown";
    expect(getFileExtension(filepath)).toBe("unknown");
    expect(checkCodeFile(filepath)).toEqual({
      isCodeFile: false,
      language: null,
    });
  });
});
