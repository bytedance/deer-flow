import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";

const galleryMock = rs.hoisted(() => ({
  search: "",
  loaded: [] as unknown[],
  replace: rs.fn(),
  pending: false,
  error: false,
}));

rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/capabilities",
  useRouter: () => ({ replace: galleryMock.replace }),
  useSearchParams: () => new URLSearchParams(galleryMock.search),
}));
rs.mock("@/core/extensions/hooks", () => ({
  useFrontendExtensions: () => ({
    data: galleryMock.loaded,
    isPending: galleryMock.pending,
    isError: galleryMock.error,
    refetch: rs.fn(),
  }),
}));
rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ locale: "en-US", t: enUS }),
}));

import { ExtensionGallery } from "@/components/workspace/capabilities/extension-gallery";
import { extensionCatalog } from "@/core/extensions/catalog";
import { enUS } from "@/core/i18n/locales/en-US";

const copy = enUS.extensions;

function contribution(overrides: Record<string, unknown>) {
  return {
    namespace: "community.bookmarks",
    module: null,
    entry: null,
    title: "Loaded title",
    description: "Loaded description",
    settings: { enabled: true },
    ...overrides,
  };
}

beforeEach(() => {
  galleryMock.pending = false;
  galleryMock.error = false;
  galleryMock.search = "";
  galleryMock.loaded = [];
  galleryMock.replace.mockClear();
});
afterEach(cleanup);

describe("extension detail", () => {
  it("shows package-owned usage and omits unspecified requirements", () => {
    galleryMock.search = "tab=extensions&extension=community.report-sections";
    render(<ExtensionGallery />);
    expect(
      screen.getByRole("heading", { name: "Assemble and download" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("heading", { name: "Before you start" }),
    ).toBeNull();
    expect(
      screen.queryByRole("heading", { name: "Workspace pages" }),
    ).toBeNull();
  });

  it("renders a backend extension's own documentation without a frontend module", () => {
    galleryMock.search = "tab=extensions&extension=company.helper";
    galleryMock.loaded = [
      contribution({
        namespace: "company.helper",
        runtime_only: true,
        documentation: {
          schema_version: 1,
          id: "company.helper",
          locales: {
            "en-US": {
              title: "Background helper",
              description: "Keeps statistics.",
              usage: [
                {
                  title: "Just run a task",
                  description: "Works automatically.",
                },
              ],
              requirements: ["Enable statistics in your deployment."],
            },
          },
        },
      }),
    ];
    render(<ExtensionGallery />);
    expect(
      screen.getByRole("heading", { name: "Background helper" }),
    ).toBeTruthy();
    expect(screen.getByText("Works automatically.")).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Before you start" }),
    ).toBeTruthy();
    expect(screen.getByText("Loaded")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /^Open / })).toBeNull();
  });
  it("opens the installed page declared by the extension, not a guessed catalog URL", () => {
    galleryMock.search = "tab=extensions&extension=community.agent-teams";
    galleryMock.loaded = [
      contribution({
        namespace: "community.agent-teams",
        extension: {
          apiVersion: 1,
          module: "teams.v1",
          surfaces: [
            {
              id: "custom-team-page",
              slot: "page",
              title: "Teams",
              mount: () => ({ dispose: () => undefined }),
            },
          ],
        },
      }),
    ];
    render(<ExtensionGallery />);
    expect(
      screen
        .getByRole("link", { name: "Open Agent teams" })
        .getAttribute("href"),
    ).toBe("/workspace/extensions/community.agent-teams/custom-team-page");
    expect(
      within(screen.getAllByRole("list")[0]!).getAllByRole("listitem"),
    ).toHaveLength(3);
  });

  it.each([
    "catalog",
    "disabled",
    "failed",
    "pending",
    "discovery-error",
    "no-page",
  ])("never offers a launch link for %s", (state) => {
    galleryMock.search = "tab=extensions&extension=community.agent-teams";
    galleryMock.pending = state === "pending";
    galleryMock.error = state === "discovery-error";
    galleryMock.loaded =
      state === "catalog"
        ? []
        : [
            contribution({
              namespace: "community.agent-teams",
              settings: { enabled: state !== "disabled" },
              error: state === "failed" ? "failed" : undefined,
              extension: {
                apiVersion: 1,
                module: "teams.v1",
                surfaces:
                  state === "no-page"
                    ? []
                    : [
                        {
                          id: "teams",
                          slot: "page",
                          title: "Teams",
                          mount: () => ({ dispose: () => undefined }),
                        },
                      ],
              },
            }),
          ];
    render(<ExtensionGallery />);
    expect(screen.queryByRole("link", { name: "Open Agent teams" })).toBeNull();
  });

  it("shows identity, catalog status and the guide for a catalog entry", () => {
    galleryMock.search = "tab=extensions&extension=community.agent-teams";
    render(<ExtensionGallery />);

    expect(
      screen.getByRole("heading", { name: copy.catalog.agentTeams.title }),
    ).toBeTruthy();
    expect(screen.getByText(copy.catalog.agentTeams.description)).toBeTruthy();
    expect(screen.getByText("deerflow-extension-agent-teams")).toBeTruthy();
    expect(screen.getByRole("button", { name: copy.all })).toBeTruthy();
    fireEvent.click(screen.getByText(copy.detail.technicalDetails));
    expect(
      screen.getByRole("button", { name: copy.detail.refresh }),
    ).toBeTruthy();

    const notice = screen.getByRole("complementary");
    expect(within(notice).getByText(copy.catalogHint)).toBeTruthy();
    expect(
      within(notice)
        .getByRole("link", { name: copy.detail.guide })
        .getAttribute("href"),
    ).toMatch(/deerflow-extension-agent-teams#readme$/);
  });

  it.each([
    ["enabled", { settings: { enabled: true } }, copy.detail.readyHint],
    ["disabled", { settings: { enabled: false } }, copy.detail.disabledHint],
  ])("explains the loaded %s state", (_name, overrides, text) => {
    galleryMock.search = "tab=extensions&extension=community.bookmarks";
    galleryMock.loaded = [contribution(overrides)];
    render(<ExtensionGallery />);

    expect(
      within(screen.getByRole("complementary")).getByText(text),
    ).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("raises a module failure as an alert", () => {
    galleryMock.search = "tab=extensions&extension=community.bookmarks";
    galleryMock.loaded = [contribution({ error: "boom" })];
    render(<ExtensionGallery />);

    expect(
      within(screen.getByRole("alert")).getByText(copy.detail.failedHint),
    ).toBeTruthy();
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("omits package and guide for an extension outside the catalog", () => {
    galleryMock.search = "tab=extensions&extension=acme.private";
    galleryMock.loaded = [contribution({ namespace: "acme.private" })];
    render(<ExtensionGallery />);

    expect(screen.getByRole("heading", { name: "Loaded title" })).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByText(/deerflow-extension-/)).toBeNull();
  });

  it("keeps the way back when the extension is unknown", () => {
    galleryMock.search = "tab=extensions&extension=missing.plugin";
    render(<ExtensionGallery />);

    expect(screen.getByText(copy.notInstalled)).toBeTruthy();
    expect(screen.getByRole("button", { name: copy.all })).toBeTruthy();
    expect(screen.queryByRole("note")).toBeNull();
  });
});

describe("extension directory", () => {
  it("keeps the reload action beside the deployment hint", () => {
    galleryMock.search = "tab=extensions";
    render(<ExtensionGallery />);

    const reload = screen.getByRole("button", { name: copy.reloadAll });
    expect(reload.parentElement).toBe(
      screen.getByText(copy.deploymentHint).parentElement,
    );
    expect(screen.getAllByRole("article")).toHaveLength(
      extensionCatalog.length,
    );
  });
});
