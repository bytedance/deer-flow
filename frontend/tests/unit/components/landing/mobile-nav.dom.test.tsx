import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { Window as HappyWindow } from "happy-dom";
import { Search } from "nextra/components";
import type { ComponentProps } from "react";

const navigation = rs.hoisted(() => ({
  pathname: "/en/docs",
  push: rs.fn(),
}));

rs.mock("next/navigation", () => ({
  usePathname: () => navigation.pathname,
  useRouter: () => ({ push: navigation.push }),
}));
rs.mock("next/link", () => ({
  default: (props: ComponentProps<"a">) => <a {...props} />,
}));

import { MobileNav } from "@/components/landing/mobile-nav";

const links = [{ href: "/en/docs", label: "Docs" }];

function menu() {
  return (
    <MobileNav links={links} search={<Search aria-label="Search docs" />} />
  );
}

async function openResults() {
  fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
  const input = screen.getByRole("combobox", { name: "Search docs" });
  fireEvent.change(input, { target: { value: "sandbox" } });
  fireEvent.keyDown(input, { key: "ArrowDown" });
  return screen.findByRole("option", { name: /Sandbox heading/ });
}

beforeEach(async () => {
  navigation.pathname = "/en/docs";
  navigation.push.mockReset();
  window.history.replaceState(null, "", "/en/docs#sandbox");
  // Happy DOM queues a hashchange for replaceState; drain setup before mount.
  await (window as unknown as HappyWindow).happyDOM.waitUntilComplete();
  Object.defineProperty(window, "pagefind", {
    configurable: true,
    value: {
      debouncedSearch: async () => ({
        results: [
          {
            data: async () => ({
              url: "/en/docs",
              meta: { title: "Docs" },
              sub_results: [
                {
                  url: "/en/docs#sandbox",
                  title: "Sandbox heading",
                  excerpt: "Run tools in an isolated sandbox.",
                },
              ],
            }),
          },
        ],
      }),
    },
  });
});

afterEach(() => {
  cleanup();
  Reflect.deleteProperty(window, "pagefind");
  rs.restoreAllMocks();
});

describe("mobile docs search", () => {
  it("closes on a route change and can reopen after navigating back", async () => {
    const { rerender } = render(menu());
    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    expect(screen.getByRole("dialog")).toBeTruthy();

    navigation.pathname = "/en/docs/harness/sandbox";
    rerender(menu());
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    navigation.pathname = "/en/docs";
    rerender(menu());
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("keeps real Nextra results inside the sheet's allowed scroll region", async () => {
    render(menu());
    const result = await openResults();
    const panel = screen.getByRole("listbox");
    expect(screen.getByRole("dialog").contains(panel)).toBe(true);

    fireEvent.pointerDown(result, { pointerType: "touch" });
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(result.isConnected).toBe(true);
  });

  it("closes after selecting a result at the already selected hash", async () => {
    render(menu());
    const result = await openResults();
    fireEvent.click(result);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(window.location.hash).toBe("#sandbox");
  });

  it("closes after keyboard selection at the already selected hash", async () => {
    render(menu());
    await openResults();
    const input = screen.getByRole("combobox", { name: "Search docs" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(window.location.hash).toBe("#sandbox");
  });

  it("closes for same-page keyboard navigation that changes the hash", async () => {
    render(menu());
    await openResults();
    fireEvent(window, new HashChangeEvent("hashchange"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("does not close while Enter is composing search text", async () => {
    render(menu());
    await openResults();
    const input = screen.getByRole("combobox", { name: "Search docs" });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.compositionStart(input);
    fireEvent.keyDown(input, { key: "Enter", isComposing: true });
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect((input as HTMLInputElement).value).toBe("sandbox");
  });

  it("keeps the menu open when a search query has no selected result", () => {
    render(menu());
    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Search docs" }), {
      target: { value: "another query" },
    });
    expect(screen.getByRole("dialog")).toBeTruthy();
  });
});
