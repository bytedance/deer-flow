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

  it.each(["pending", "error"] as const)(
    "waits for discovery before declaring an unknown extension not installed while %s",
    (state) => {
      galleryMock.search = "tab=extensions&extension=acme.private";
      galleryMock.pending = state === "pending";
      galleryMock.error = state === "error";
      render(<ExtensionGallery />);

      expect(screen.queryByText(copy.notInstalled)).toBeNull();
      expect(
        screen.getByText(state === "pending" ? copy.loading : copy.unavailable),
      ).toBeTruthy();
    },
  );
});

describe("extension directory", () => {
  it("groups catalog entries by scenario and collapses developer examples by default", () => {
    galleryMock.search = "tab=extensions";
    render(<ExtensionGallery />);

    expect(screen.getByRole("button", { name: copy.reloadAll })).toBeTruthy();
    expect(screen.getByText(copy.deploymentHint)).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: copy.directory.catalogTitle }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("heading", { name: copy.directory.installedTitle }),
    ).toBeNull();
    // 16 production catalog entries visible; 3 developer examples start collapsed.
    const productionCount = extensionCatalog.filter(
      (item) =>
        item.key !== "example" &&
        item.key !== "retrieval" &&
        item.key !== "knowledge",
    ).length;
    expect(screen.getAllByRole("article")).toHaveLength(productionCount);
    expect(
      screen.getAllByRole("button", {
        name: copy.view(copy.catalog.agentTeams.title),
      }),
    ).toHaveLength(1);

    const toggle = screen.getByRole("button", {
      name: new RegExp(copy.directory.examplesTitle),
    });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getAllByRole("article")).toHaveLength(
      extensionCatalog.length,
    );
  });

  it("pins installed extensions above the catalog with status ordering and direct page links", () => {
    galleryMock.search = "tab=extensions";
    galleryMock.loaded = [
      contribution({
        namespace: "community.bookmarks",
        settings: { enabled: false },
      }),
      contribution({
        namespace: "community.agent-teams",
        settings: { enabled: true },
        extension: {
          apiVersion: 1,
          module: "teams.v1",
          surfaces: [
            {
              id: "teams",
              slot: "page",
              title: "Teams",
              mount: () => ({ dispose: () => undefined }),
            },
          ],
        },
      }),
      contribution({
        namespace: "acme.broken",
        title: "Broken internal plugin",
        description: "Failed to load browser bundle.",
        error: "failed",
      }),
    ];
    render(<ExtensionGallery />);

    const installedSection = screen
      .getByRole("heading", { name: copy.directory.installedTitle })
      .closest("section")!;
    const installedCards = within(installedSection).getAllByRole("article");
    expect(installedCards).toHaveLength(3);
    // Ordered: failed -> enabled -> disabled.
    expect(installedCards[0]!.textContent).toContain("Broken internal plugin");
    expect(installedCards[1]!.textContent).toContain(
      copy.catalog.agentTeams.title,
    );
    expect(installedCards[2]!.textContent).toContain(
      copy.catalog.bookmarks.title,
    );
    expect(
      within(installedCards[1]!)
        .getByRole("link", { name: copy.open(copy.catalog.agentTeams.title) })
        .getAttribute("href"),
    ).toBe("/workspace/extensions/community.agent-teams/teams");
    expect(
      screen.getAllByRole("button", {
        name: copy.view(copy.catalog.agentTeams.title),
      }),
    ).toHaveLength(1);

    // Installed catalog items are not duplicated in the available catalog section.
    const catalogSection = screen
      .getByRole("heading", { name: copy.directory.catalogTitle })
      .closest("section")!;
    expect(
      within(catalogSection).queryByText(copy.catalog.agentTeams.title),
    ).toBeNull();
    expect(
      within(catalogSection).queryByText(copy.catalog.bookmarks.title),
    ).toBeNull();

    // Uncategorized custom plugin reveals the "Other" category pill.
    const otherPill = screen.getByRole("button", {
      name: copy.directory.categories.other,
    });
    fireEvent.click(otherPill);
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(screen.getByText("Broken internal plugin")).toBeTruthy();
  });

  it("renders a non-interactive Examples heading during search and preserves saved disclosure state", () => {
    galleryMock.search = "tab=extensions";
    const { rerender } = render(<ExtensionGallery query="" />);

    const initialToggle = screen.getByRole("button", {
      name: new RegExp(copy.directory.examplesTitle),
    });
    expect(initialToggle.getAttribute("aria-expanded")).toBe("false");

    rerender(<ExtensionGallery query="sample documents" />);
    expect(screen.getByText(copy.catalog.knowledge.title)).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: copy.directory.examplesTitle }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", {
        name: new RegExp(copy.directory.examplesTitle),
      }),
    ).toBeNull();

    // Clearing the search restores the collapsible button in its saved collapsed state.
    rerender(<ExtensionGallery query="" />);
    const restoredCollapsed = screen.getByRole("button", {
      name: new RegExp(copy.directory.examplesTitle),
    });
    expect(restoredCollapsed.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(copy.catalog.knowledge.title)).toBeNull();

    // Manually expanding before searching preserves the expanded state after clearing.
    fireEvent.click(restoredCollapsed);
    expect(restoredCollapsed.getAttribute("aria-expanded")).toBe("true");
    rerender(<ExtensionGallery query="sample documents" />);
    expect(
      screen.queryByRole("button", {
        name: new RegExp(copy.directory.examplesTitle),
      }),
    ).toBeNull();
    rerender(<ExtensionGallery query="" />);
    const restoredExpanded = screen.getByRole("button", {
      name: new RegExp(copy.directory.examplesTitle),
    });
    expect(restoredExpanded.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText(copy.catalog.knowledge.title)).toBeTruthy();
  });

  it.each(["pending", "error"] as const)(
    "waits for discovery before declaring Installed empty while %s",
    (state) => {
      galleryMock.search = "tab=extensions";
      galleryMock.pending = state === "pending";
      galleryMock.error = state === "error";
      const { rerender } = render(<ExtensionGallery />);

      const installedTab = screen.getByRole("tab", {
        name: new RegExp(copy.directory.installed),
      });
      fireEvent.mouseDown(installedTab, { button: 0, ctrlKey: false });
      fireEvent.click(installedTab);

      expect(
        screen.getByText(state === "pending" ? copy.loading : copy.unavailable),
      ).toBeTruthy();
      expect(screen.queryByText(copy.directory.installedEmpty)).toBeNull();
      expect(
        screen.queryByText(copy.directory.installedFilteredEmpty),
      ).toBeNull();
      expect(
        screen.queryByRole("heading", { name: copy.directory.installedTitle }),
      ).toBeNull();

      // Once discovery succeeds with zero extensions, the empty inventory message appears.
      galleryMock.pending = false;
      galleryMock.error = false;
      rerender(<ExtensionGallery />);
      const installedSection = screen
        .getByRole("heading", { name: copy.directory.installedTitle })
        .closest("section")!;
      expect(
        within(installedSection).getByText(copy.directory.installedEmpty),
      ).toBeTruthy();
    },
  );

  it.each(["pending", "error"] as const)(
    "does not label installed cards as disabled while discovery is %s",
    (state) => {
      galleryMock.search = "tab=extensions";
      galleryMock.pending = state === "pending";
      galleryMock.error = state === "error";
      galleryMock.loaded = [
        contribution({
          namespace: "community.agent-teams",
          settings: { enabled: true },
          extension: {
            apiVersion: 1,
            module: "teams.v1",
            surfaces: [
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

      const installedTab = screen.getByRole("tab", {
        name: new RegExp(copy.directory.installed),
      });
      expect(installedTab.textContent).toBe(copy.directory.installed);

      const installedSection = screen
        .getByRole("heading", { name: copy.directory.installedTitle })
        .closest("section")!;
      expect(
        within(installedSection).queryByText(enUS.capabilities.disabled),
      ).toBeNull();
      expect(
        within(installedSection).getByText(
          state === "pending" ? copy.loading : copy.unavailable,
        ),
      ).toBeTruthy();
      expect(
        within(installedSection).queryByRole("link", {
          name: copy.open(copy.catalog.agentTeams.title),
        }),
      ).toBeNull();
    },
  );

  it("reveals the Examples filter pill when an example extension is installed and lets filtered empty states reset", () => {
    galleryMock.search = "tab=extensions";
    galleryMock.loaded = [
      contribution({
        namespace: "example.retrieval",
        settings: { enabled: true },
      }),
    ];
    render(<ExtensionGallery />);

    const examplesPill = screen.getByRole("button", {
      name: copy.directory.categories.examples,
    });
    fireEvent.click(examplesPill);
    const installedSection = screen
      .getByRole("heading", { name: copy.directory.installedTitle })
      .closest("section")!;
    expect(
      within(installedSection).getByText(copy.catalog.retrieval.title),
    ).toBeTruthy();
    // Remaining uninstalled examples stay accessible under a non-interactive heading while the Examples pill is active.
    expect(screen.getByText(copy.catalog.example.title)).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: copy.directory.examplesTitle }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", {
        name: new RegExp(copy.directory.examplesTitle),
      }),
    ).toBeNull();

    // Returning to All categories restores the interactive disclosure toggle in its saved collapsed state.
    fireEvent.click(
      screen.getByRole("button", { name: copy.directory.allCategories }),
    );
    const restoredToggle = screen.getByRole("button", {
      name: new RegExp(copy.directory.examplesTitle),
    });
    expect(restoredToggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(copy.catalog.example.title)).toBeNull();

    // Filtering Installed view to a category with 0 installed matches offers a reset button.
    fireEvent.click(
      screen.getByRole("button", {
        name: copy.directory.categories.knowledge,
      }),
    );
    const installedTab = screen.getByRole("tab", {
      name: new RegExp(copy.directory.installed),
    });
    fireEvent.mouseDown(installedTab, { button: 0, ctrlKey: false });
    fireEvent.click(installedTab);
    const emptySection = screen
      .getByRole("heading", { name: copy.directory.installedTitle })
      .closest("section")!;
    expect(
      within(emptySection).getByText(copy.directory.installedFilteredEmpty),
    ).toBeTruthy();
    fireEvent.click(
      within(emptySection).getByRole("button", {
        name: copy.directory.allCategories,
      }),
    );
    expect(
      within(emptySection).getByText(copy.catalog.retrieval.title),
    ).toBeTruthy();
  });
});
