import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { PropsWithChildren } from "react";

import { KnowledgeScopeSelector } from "@/components/workspace/knowledge-scope-selector";
import { I18nProvider } from "@/core/i18n/context";
import type { KnowledgeScopeSelection } from "@/core/knowledge";

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

function renderSelector(selection: KnowledgeScopeSelection) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  function Wrapper({ children }: PropsWithChildren) {
    return (
      <QueryClientProvider client={queryClient}>
        <I18nProvider initialLocale="en-US">{children}</I18nProvider>
      </QueryClientProvider>
    );
  }

  return render(
    <KnowledgeScopeSelector
      agentName="researcher"
      selection={selection}
      onChange={() => undefined}
    />,
    { wrapper: Wrapper },
  );
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.href;
  return input.url;
}

describe("KnowledgeScopeSelector trigger", () => {
  it("renders only the icon and stays highlighted while retrieval is active", () => {
    renderSelector({ mode: "all" });

    const trigger = screen.getByRole("button", { name: "Knowledge · All" });
    expect(trigger.textContent).toBe("");
    expect(trigger.getAttribute("aria-pressed")).toBe("true");
    expect(trigger.className).toContain("bg-primary/10");
    expect(trigger.querySelector("svg")).not.toBeNull();
  });

  it("returns to the neutral icon state when retrieval is off", () => {
    renderSelector({ mode: "disabled" });

    const trigger = screen.getByRole("button", { name: "Knowledge · Off" });
    expect(trigger.textContent).toBe("");
    expect(trigger.getAttribute("aria-pressed")).toBe("false");
    expect(trigger.className).not.toContain("bg-primary/10");
    expect(trigger.querySelector("svg")).not.toBeNull();
  });

  it("does not load documents while an expanded dataset still uses all files", async () => {
    const fetch = rs.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = requestUrl(input);
      return Promise.resolve(
        Response.json({
          items: url.includes("/documents?")
            ? [{ id: "document-1", name: "Guide", selectable: true }]
            : [{ id: "dataset-1", name: "Policies", selectable: true }],
          page: 1,
          page_size: 100,
          total: 1,
        }),
      );
    });
    renderSelector({
      mode: "selected",
      datasets: [
        {
          id: "dataset-1",
          name: "Policies",
          documents: { mode: "all" },
        },
      ],
    });

    fireEvent.click(screen.getByRole("button", { name: "Knowledge · 1 base" }));
    await screen.findByText("Policies");
    fireEvent.click(screen.getByRole("button", { name: "Files" }));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(
      fetch.mock.calls.some(([input]) =>
        requestUrl(input).includes("/documents?"),
      ),
    ).toBe(false);

    fireEvent.click(screen.getByRole("radio", { name: "Selected files" }));
    await waitFor(() => {
      expect(
        fetch.mock.calls.some(([input]) =>
          requestUrl(input).includes("/documents?"),
        ),
      ).toBe(true);
    });
  });
});
