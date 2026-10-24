import { afterEach, expect, it, rs } from "@rstest/core";

import AuthLayout from "@/app/(auth)/layout";
import WorkspaceLayout from "@/app/workspace/layout";
import type { AuthResult } from "@/core/auth/types";

const fixture = rs.hoisted(() => ({
  route: "",
  auth: { tag: "unauthenticated" } as AuthResult,
}));
rs.mock("next/headers", () => ({
  headers: async () =>
    new Headers({ "x-deerflow-request-route": fixture.route }),
  cookies: async () => ({ get: () => undefined }),
}));
rs.mock("next/navigation", () => ({
  redirect: (href: string) => {
    throw new Error("redirect:" + href);
  },
  useRouter: () => ({ push: rs.fn() }),
  usePathname: () => "/workspace",
}));
rs.mock("@/core/auth/server", () => ({
  getServerSideUser: async () => fixture.auth,
}));
rs.mock("@/core/i18n/server", () => ({
  detectLocaleServer: async () => "en-US",
}));
rs.mock("@/app/workspace/workspace-content", () => ({
  WorkspaceContent: () => <span>private</span>,
}));
afterEach(() => {
  fixture.auth = { tag: "unauthenticated" };
  fixture.route = "";
});
it("keeps a copied team/resource URI through server login redirect and an already-authenticated login entry", async () => {
  const target =
    "/workspace/chats/private?workspace_id=22222222-2222-2222-2222-222222222222&tab=files";
  fixture.route = target;
  await expect(
    WorkspaceLayout({ children: <span>private</span> }),
  ).rejects.toThrow("redirect:/login?next=" + encodeURIComponent(target));
  fixture.auth = {
    tag: "authenticated",
    user: {
      id: "alice",
      email: "alice@example.test",
      system_role: "user",
      needs_setup: false,
    },
  };
  fixture.route = "/login?next=" + encodeURIComponent(target);
  await expect(AuthLayout({ children: <span>login</span> })).rejects.toThrow(
    "redirect:" + target,
  );
});

it("retains the native safe-next policy for artifact returns, unsafe targets and auth-entry loops", async () => {
  fixture.auth = {
    tag: "authenticated",
    user: {
      id: "alice",
      email: "alice@example.test",
      system_role: "user",
      needs_setup: false,
    },
  };
  const artifact =
    "/artifacts/view?thread_id=private&path=report.md&workspace_id=22222222-2222-2222-2222-222222222222";
  for (const [target, expected] of [
    [artifact, artifact],
    ["https://outside.invalid/workspace", "/workspace"],
    ["//outside.invalid/workspace", "/workspace"],
    ["/login", "/workspace"],
    ["/setup", "/workspace"],
  ]) {
    fixture.route = "/login?next=" + encodeURIComponent(target!);
    await expect(AuthLayout({ children: <span>login</span> })).rejects.toThrow(
      "redirect:" + expected,
    );
  }
  fixture.route = "/login?next=%2Fworkspace%2Fa&next=%2Fworkspace%2Fb";
  await expect(AuthLayout({ children: <span>login</span> })).rejects.toThrow(
    "redirect:/workspace",
  );
});
