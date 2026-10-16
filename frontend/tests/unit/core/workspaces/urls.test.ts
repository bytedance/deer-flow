import { describe, expect, it } from "@rstest/core";

import { workspaceHref, workspaceSelector } from "@/core/workspaces/urls";

const P = "11111111-1111-1111-1111-111111111111";
const T = "22222222-2222-2222-2222-222222222222";
describe("workspace navigation locators", () => {
  it("carries the locator through native string/object paths without mutating query inputs", () => {
    expect(workspaceHref("/workspace/chats/thread?tab=files#source", T)).toBe(
      `/workspace/chats/thread?tab=files&workspace_id=${T}#source`,
    );
    const input = {
      pathname: "/workspace/projects/project",
      query: { tab: ["files", "sources"] },
      hash: "heading",
    };
    expect(workspaceHref(input, T)).toEqual({
      ...input,
      query: { ...input.query, workspace_id: T },
    });
    expect(input.query).toEqual({ tab: ["files", "sources"] });
    expect(
      workspaceHref(
        { pathname: "/workspace/chats/new", query: "project=p" },
        T,
      ),
    ).toEqual({
      pathname: "/workspace/chats/new",
      query: `project=p&workspace_id=${T}`,
    });
    expect(
      workspaceHref({ pathname: "/workspace", search: "?tab=recent" }, T),
    ).toEqual({
      pathname: "/workspace",
      search: `?tab=recent&workspace_id=${T}`,
    });
    expect(workspaceHref("/workspace/chats/new")).toBe("/workspace/chats/new");
  });
  it("preserves explicit selectors and never adds one to an external, API or public destination", () => {
    for (const path of [
      `/workspace?workspace_id=${P}`,
      "/workspace?workspace_id=",
      `/workspace?workspace_id=${P}&workspace_id=${T}`,
      "https://other.test/workspace",
      "//other.test/workspace",
      "/\\other.test/workspace",
      "/api/workspaces",
      "/workspace/../api",
      "/login?next=%2Fworkspace",
      "/showcase/chat",
      "mailto:a@example.test",
    ])
      expect(workspaceHref(path, T)).toBe(path);
    for (const input of [
      { pathname: "/workspace", host: "other.test" },
      { pathname: "/\\other.test/workspace" },
      { pathname: "/workspace", search: `?workspace_id=${P}` },
      { pathname: "/workspace", query: { workspace_id: P } },
    ])
      expect(workspaceHref(input, T)).toBe(input);
  });
  it("distinguishes absent from invalid or repeated route selectors", () => {
    expect(workspaceSelector(new URLSearchParams())).toBeUndefined();
    expect(workspaceSelector(new URLSearchParams({ workspace_id: T }))).toBe(T);
    for (const query of [
      "workspace_id=",
      "workspace_id=not-a-space",
      `workspace_id=${P}&workspace_id=${T}`,
    ])
      expect(workspaceSelector(new URLSearchParams(query))).toBe("");
  });
});
