import { describe, expect, test } from "@rstest/core";

import { getDevBundler, getNextDevArgs } from "../../../scripts/dev.mjs";

describe("frontend dev launcher", () => {
  test("uses webpack on Windows to avoid Turbopack runtime instability", () => {
    expect(getDevBundler("win32")).toBe("webpack");
    expect(getNextDevArgs("win32")).toEqual(["dev", "--webpack"]);
  });

  test("passes through extra Next.js arguments", () => {
    expect(getNextDevArgs("win32", ["--", "--port", "3302"])).toEqual([
      "dev",
      "--webpack",
      "--port",
      "3302",
    ]);
  });

  test("keeps Turbopack for non-Windows development", () => {
    expect(getDevBundler("linux")).toBe("turbo");
    expect(getDevBundler("darwin")).toBe("turbo");
    expect(getNextDevArgs("linux")).toEqual(["dev", "--turbo"]);
  });
});
