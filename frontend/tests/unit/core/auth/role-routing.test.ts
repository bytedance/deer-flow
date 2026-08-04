import { describe, expect, it } from "@rstest/core";

import { getWorkspaceHomePath } from "@/core/auth/role-routing";

describe("getWorkspaceHomePath", () => {
  it("sends administrators to the operations console", () => {
    expect(getWorkspaceHomePath("admin")).toBe("/workspace/admin");
  });

  it("sends ordinary users to a new conversation", () => {
    expect(getWorkspaceHomePath("user")).toBe("/workspace/chats/new");
  });
});
