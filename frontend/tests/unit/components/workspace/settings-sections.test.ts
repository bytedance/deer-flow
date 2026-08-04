import { expect, test } from "@rstest/core";

import { getVisibleSettingsSectionIds } from "@/components/workspace/settings/settings-sections";

test("does not expose the about setting to ordinary users", () => {
  expect(getVisibleSettingsSectionIds("user")).not.toContain("about");
});

test("does not expose personal workspace settings to administrators", () => {
  expect(getVisibleSettingsSectionIds("admin")).toEqual(["account"]);
});
