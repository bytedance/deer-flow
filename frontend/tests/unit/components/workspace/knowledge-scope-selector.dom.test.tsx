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
    expect(trigger.className).toContain("text-foreground");
    expect(trigger.className).not.toContain("bg-primary/10");
    expect(trigger.className).not.toContain("border-primary/20");
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
      if (url.includes("/capabilities?"))
        return Promise.resolve(
          Response.json({
            operations: [
              "search",
              "catalog",
              "documents",
              "dataset_filter",
              "document_filter",
            ],
            scope_selection_enabled: true,
          }),
        );
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

  it("allows dataset selection without exposing unsupported document filtering", async () => {
    const fetch = rs.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const url = requestUrl(input);
      return Promise.resolve(
        Response.json(
          url.includes("/capabilities?")
            ? {
                operations: ["search", "catalog", "dataset_filter"],
                scope_selection_enabled: true,
              }
            : {
                items: [
                  { id: "dataset-1", name: "Policies", selectable: true },
                ],
                page: 1,
                page_size: 100,
                total: 1,
              },
        ),
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
    expect(screen.queryByRole("button", { name: "Files" })).toBeNull();
    expect(
      fetch.mock.calls.some(([input]) =>
        requestUrl(input).includes("/documents?"),
      ),
    ).toBe(false);
  });

  it("preserves a stale document selection and blocks Apply when filtering is unsupported", async () => {
    rs.spyOn(globalThis, "fetch").mockImplementation((input) =>
      Promise.resolve(
        Response.json(
          requestUrl(input).includes("/capabilities?")
            ? {
                operations: ["search", "catalog", "dataset_filter"],
                scope_selection_enabled: true,
              }
            : {
                items: [
                  { id: "dataset-1", name: "Policies", selectable: true },
                ],
                page: 1,
                page_size: 100,
                total: 1,
              },
        ),
      ),
    );
    renderSelector({
      mode: "selected",
      datasets: [
        {
          id: "dataset-1",
          name: "Policies",
          documents: {
            mode: "selected",
            items: [{ id: "doc-1", name: "Private file" }],
          },
        },
      ],
    });
    fireEvent.click(screen.getByTestId("knowledge-scope-trigger"));
    await screen.findByText("Policies");
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "Apply" }).disabled,
    ).toBe(true);
  });
});
