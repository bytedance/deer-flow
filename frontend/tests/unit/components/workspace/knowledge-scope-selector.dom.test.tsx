import { afterEach, describe, expect, it } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import type { PropsWithChildren } from "react";

import { KnowledgeScopeSelector } from "@/components/workspace/knowledge-scope-selector";
import { I18nProvider } from "@/core/i18n/context";
import type { KnowledgeScopeSelection } from "@/core/knowledge";

afterEach(cleanup);

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
});
