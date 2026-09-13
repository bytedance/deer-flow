import { afterEach, describe, expect, rs, test } from "@rstest/core";

import { type AuthResult } from "@/core/auth/types";

const USER = {
  id: "user-1",
  email: "admin@example.com",
  system_role: "admin" as const,
  needs_setup: false,
};

const authState: { result: AuthResult } = {
  result: { tag: "authenticated", user: USER },
};

rs.mock("@/core/auth/server", () => ({
  getServerSideUser: rs.fn(async () => authState.result),
}));

async function loadHomePage() {
  rs.resetModules();
  return (await import("@/app/page")).default;
}

// next/navigation redirect() throws NEXT_REDIRECT errors with the target
// encoded in the digest — exactly how App Router layouts assert redirects.
async function expectRedirectTo(target: string) {
  const HomePage = await loadHomePage();
  try {
    await HomePage();
    expect.unreachable(`expected a redirect to ${target}`);
  } catch (error) {
    expect(error).toBeInstanceOf(Error);
    expect((error as Error).message).toContain("NEXT_REDIRECT");
    expect((error as { digest?: string }).digest).toContain(target);
  }
}

describe("root home page (issue #3909)", () => {
  afterEach(() => {
    rs.unstubAllEnvs();
  });

  test("sends first-boot installs straight to /setup", async () => {
    authState.result = { tag: "system_setup_required" };
    await expectRedirectTo("/setup");
  });

  test("sends authenticated users to /workspace", async () => {
    authState.result = { tag: "authenticated", user: USER };
    await expectRedirectTo("/workspace");
  });

  test("sends unauthenticated visitors to /login", async () => {
    authState.result = { tag: "unauthenticated" };
    await expectRedirectTo("/login");
  });
});
