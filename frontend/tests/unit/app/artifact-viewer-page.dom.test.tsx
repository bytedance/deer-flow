import { afterEach, expect, rs, test } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";
import { type ReactNode, useContext } from "react";

const mocks = rs.hoisted(() => ({
  getUser: rs.fn(),
  redirect: rs.fn((url: string) => {
    throw new Error(`NEXT_REDIRECT ${url}`);
  }),
}));
rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn() }),
  usePathname: () => "/artifacts/view",
  redirect: mocks.redirect,
}));
rs.mock("@/core/auth/server", () => ({ getServerSideUser: mocks.getUser }));
rs.mock("@/core/static-mode", () => ({ isStaticWebsiteOnly: () => false }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/components/query-client-provider", () => ({
  QueryClientProvider: ({ children }: { children: ReactNode }) => children,
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));
rs.mock("@/core/i18n/server", () => ({ getI18n: async () => ({ t: enUS }) }));
rs.mock("@/components/workspace/artifacts/artifact-viewer", () => ({
  ArtifactViewer: (props: {
    filepath: string;
    threadId: string;
    isMock: boolean;
  }) => {
    const { user } = useAuth();
    const scope = useContext(AuthQueryScopeContext);
    return (
      <>
        <output>{`${user?.id ?? "public"}:${String(scope)}`}</output>
        <ArtifactDownloadButton {...props} />
      </>
    );
  },
}));

import ArtifactViewerPage from "@/app/artifacts/view/page";
import { ArtifactDownloadButton } from "@/components/workspace/artifacts/artifact-download-button";
import { useAuth } from "@/core/auth/AuthProvider";
import { AuthQueryScopeContext } from "@/core/auth/query-scope";
import { enUS } from "@/core/i18n/locales/en-US";

const publicTarget = {
  path: "/mnt/user-data/outputs/fei-fei-li-podcast-timeline.md",
  thread_id: "3823e443-4e2b-4679-b496-a9506eae462b",
  mock: "true",
};
afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

test("public showcase downloads render with auth context without an auth lookup or logout verdict", async () => {
  render(
    await ArtifactViewerPage({ searchParams: Promise.resolve(publicTarget) }),
  );
  expect(
    screen.getByRole("button", {
      name: /Download fei-fei-li-podcast-timeline.md/,
    }),
  ).toBeTruthy();
  expect(screen.getByText("public:undefined")).toBeTruthy();
  expect(mocks.getUser).not.toHaveBeenCalled();
  expect(mocks.redirect).not.toHaveBeenCalled();
});

test("private viewer keeps the authenticated user's provider", async () => {
  mocks.getUser.mockResolvedValue({
    tag: "authenticated",
    user: {
      id: "owner",
      email: "owner@example.com",
      system_role: "user",
      needs_setup: false,
      oauth_provider: null,
    },
  });
  render(
    await ArtifactViewerPage({
      searchParams: Promise.resolve({ ...publicTarget, mock: "false" }),
    }),
  );
  expect(screen.getByText("owner:owner")).toBeTruthy();
});

test("private viewer still requires login without a session", async () => {
  mocks.getUser.mockResolvedValue({ tag: "unauthenticated" });
  await expect(
    ArtifactViewerPage({
      searchParams: Promise.resolve({ ...publicTarget, mock: "false" }),
    }),
  ).rejects.toThrow("NEXT_REDIRECT /login?next=");
});
