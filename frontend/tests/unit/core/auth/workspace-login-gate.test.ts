import { expect, test, afterEach } from "vitest";

import {
  isWorkspaceLoginRequiredSync,
  setWorkspaceLoginRequired,
} from "@/core/auth/workspace-login-gate";

afterEach(() => {
  setWorkspaceLoginRequired(false);
});

test("setWorkspaceLoginRequired toggles sync flag", () => {
  expect(isWorkspaceLoginRequiredSync()).toBe(false);
  setWorkspaceLoginRequired(true);
  expect(isWorkspaceLoginRequiredSync()).toBe(true);
});
