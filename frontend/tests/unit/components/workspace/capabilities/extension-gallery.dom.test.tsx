import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen, within } from "@testing-library/react";

const galleryMock = rs.hoisted(() => ({
  search: "",
  loaded: [] as unknown[],
  replace: rs.fn(),
}));

rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/capabilities",
  useRouter: () => ({ replace: galleryMock.replace }),
  useSearchParams: () => new URLSearchParams(galleryMock.search),
}));
rs.mock("@/core/extensions/hooks", () => ({
  useFrontendExtensions: () => ({
    data: galleryMock.loaded,
    isPending: false,
    isError: false,
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
  galleryMock.search = "";
  galleryMock.loaded = [];
  galleryMock.replace.mockClear();
});
afterEach(cleanup);

describe("extension detail", () => {
  it("shows identity, catalog status and the guide for a catalog entry", () => {
    galleryMock.search = "tab=extensions&extension=community.agent-teams";
    render(<ExtensionGallery />);

    expect(
      screen.getByRole("heading", { name: copy.catalog.agentTeams.title }),
    ).toBeTruthy();
    expect(screen.getByText(copy.catalog.agentTeams.description)).toBeTruthy();
    expect(screen.getByText("deerflow-extension-agent-teams")).toBeTruthy();
    expect(screen.getByRole("button", { name: copy.all })).toBeTruthy();
    expect(screen.getByRole("button", { name: copy.reloadAll })).toBeTruthy();

    const notice = screen.getByRole("note");
    expect(within(notice).getByText(copy.catalogHint)).toBeTruthy();
    expect(
      within(notice)
        .getByRole("link", { name: copy.installationGuide })
        .getAttribute("href"),
    ).toMatch(/deerflow-extension-agent-teams#readme$/);
  });

  it.each([
    ["enabled", { settings: { enabled: true } }, copy.enabledManaged],
    ["disabled", { settings: { enabled: false } }, copy.disabledManaged],
  ])("reports a loaded %s extension as a note", (_name, overrides, text) => {
    galleryMock.search = "tab=extensions&extension=community.bookmarks";
    galleryMock.loaded = [contribution(overrides)];
    render(<ExtensionGallery />);

    expect(within(screen.getByRole("note")).getByText(text)).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("raises a module failure as an alert", () => {
    galleryMock.search = "tab=extensions&extension=community.bookmarks";
    galleryMock.loaded = [contribution({ error: "boom" })];
    render(<ExtensionGallery />);

    expect(
      within(screen.getByRole("alert")).getByText(copy.moduleUnavailable),
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
