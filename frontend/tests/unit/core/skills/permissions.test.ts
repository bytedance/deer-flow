import { beforeEach, describe, expect, rs, test } from "@rstest/core";

const mocks = rs.hoisted(() => ({ staticWebsite: rs.fn() }));
rs.mock("@/core/static-mode", () => ({
  isStaticWebsiteOnly: mocks.staticWebsite,
}));

import type { SkillManagementFeature } from "@/core/features/api";
import {
  canInstallSkillFromSource,
  canManageSkills,
} from "@/core/skills/permissions";

const capability = (
  canManage: boolean,
  sourceAvailable = false,
): SkillManagementFeature => ({
  lifecycle_permissions: true,
  can_manage: canManage,
  source_install_available: sourceAvailable,
});

beforeEach(() => {
  mocks.staticWebsite.mockReset().mockReturnValue(false);
});

describe("skill management capability", () => {
  test.each([
    { role: "user", canManage: true, expected: true },
    { role: "user", canManage: false, expected: false },
    { role: "admin", canManage: false, expected: false },
  ])(
    "uses can_manage for $role when the new capability exists",
    ({ role, canManage, expected }) => {
      expect(
        canManageSkills({ system_role: role }, capability(canManage)),
      ).toBe(expected);
    },
  );

  test.each([undefined, null])(
    "falls back to the role only for an old capability value %s",
    (feature) => {
      expect(canManageSkills({ system_role: "admin" }, feature)).toBe(true);
      expect(canManageSkills({ system_role: "user" }, feature)).toBe(false);
      expect(canInstallSkillFromSource(feature)).toBe(false);
    },
  );

  test("static websites override roles, capabilities, and source availability", () => {
    mocks.staticWebsite.mockReturnValue(true);
    expect(
      canManageSkills({ system_role: "admin" }, capability(true, true)),
    ).toBe(false);
    expect(canManageSkills({ system_role: "admin" }, undefined)).toBe(false);
    expect(canInstallSkillFromSource(capability(true, true))).toBe(false);
  });
});
