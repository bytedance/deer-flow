import { afterEach, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";

import { ExtensionGallery } from "@/components/workspace/capabilities/extension-gallery";
import { enUS } from "@/core/i18n/locales/en-US";

const navigation = rs.hoisted(() => ({
  selected: "",
  replace: rs.fn(),
}));

rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/capabilities",
  useRouter: () => ({ replace: navigation.replace }),
  useSearchParams: () =>
    new URLSearchParams(
      navigation.selected
        ? `tab=extensions&extension=${navigation.selected}`
        : "tab=extensions",
    ),
}));
rs.mock("@/core/extensions/hooks", () => ({
  useFrontendExtensions: () => ({
    data: [],
    isPending: false,
    isError: false,
  }),
}));
rs.mock("@/core/i18n/hooks", () => ({ useI18n: () => ({ t: enUS }) }));

afterEach(() => {
  cleanup();
  document.body.replaceChildren();
  navigation.selected = "";
  navigation.replace.mockClear();
});

it("keeps catalog navigation disabled in SSR until its own hydration", () => {
  const container = document.createElement("div");
  container.innerHTML = renderToString(<ExtensionGallery />);
  document.body.append(container);

  expect(container.querySelectorAll("article").length).toBe(6);
  const buttons = [...container.querySelectorAll("button")];
  expect(buttons.length).toBe(13);
  expect(buttons.every((button) => button.disabled)).toBe(true);

  render(<ExtensionGallery />, { container, hydrate: true });
  const view = screen.getByRole("button", { name: "View Agent teams" });
  expect((view as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(view);
  expect(navigation.replace).toHaveBeenCalledTimes(1);
  expect(navigation.replace).toHaveBeenCalledWith(
    "/workspace/capabilities?tab=extensions&extension=community.agent-teams",
    { scroll: false },
  );
});

it("keeps detail navigation disabled in SSR and enables it after hydration", () => {
  navigation.selected = "community.agent-teams";
  const container = document.createElement("div");
  container.innerHTML = renderToString(<ExtensionGallery />);
  document.body.append(container);
  expect(container.querySelector("h2")?.textContent).toBe("Agent teams");
  expect(
    [...container.querySelectorAll("button")].every(
      (button) => button.disabled,
    ),
  ).toBe(true);
  // The documentation link is a real anchor, usable without client JavaScript.
  expect(container.querySelector("a")?.getAttribute("href")).toMatch(
    /deerflow-extension-agent-teams#readme$/,
  );
  render(<ExtensionGallery />, { container, hydrate: true });
  fireEvent.click(screen.getByRole("button", { name: "All extensions" }));
  expect(navigation.replace).toHaveBeenCalledWith(
    "/workspace/capabilities?tab=extensions",
    { scroll: false },
  );
});
