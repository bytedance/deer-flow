import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ProjectMemorySection } from "@/components/workspace/projects/project-memory-section";
import { I18nProvider } from "@/core/i18n/context";

const mocks = rs.hoisted(() => ({
  mutate: rs.fn(),
  pending: false,
  error: false,
}));
rs.mock("@/core/projects/memory", () => ({
  useProjectMemory: () => ({
    data: {
      enabled: true,
      max_facts: 30,
      facts: [
        {
          id: "f1",
          content: "Use API v2",
          source_thread_id: "t1",
          created_at: "2026-11-10",
        },
      ],
    },
    isError: mocks.error,
    refetch: rs.fn(),
  }),
  useProjectMemoryAction: () => ({
    mutate: mocks.mutate,
    isPending: mocks.pending,
  }),
}));

const project = {
  id: "p1",
  name: "Finance",
  instructions: "Use Chinese",
  status: "active" as const,
  presentation: {},
  created_at: "",
  updated_at: "",
};
function show(dirty = false, maxBytes = 8192) {
  return render(
    <I18nProvider initialLocale="en-US">
      <ProjectMemorySection
        project={project}
        hasUnsavedInstructions={dirty}
        maxBytes={maxBytes}
      />
    </I18nProvider>,
  );
}
beforeEach(() => {
  mocks.mutate.mockClear();
  mocks.pending = false;
  mocks.error = false;
});
afterEach(cleanup);

describe("Project memory controls", () => {
  it("sends the saved instruction value when promoting and exposes deletion", () => {
    show();
    fireEvent.click(
      screen.getByRole("button", { name: "Move to instructions" }),
    );
    expect(mocks.mutate).toHaveBeenCalledWith(
      { kind: "promote", factId: "f1", instructions: "Use Chinese" },
      expect.any(Object),
    );
    fireEvent.click(screen.getByRole("button", { name: "Delete: Use API v2" }));
    expect(mocks.mutate).toHaveBeenCalledWith(
      { kind: "delete", factId: "f1" },
      expect.any(Object),
    );
  });
  it("blocks promotion while instructions are dirty or would exceed the cap", () => {
    const view = show(true);
    expect(
      screen
        .getByRole("button", {
          name: "Move to instructions",
        })
        .hasAttribute("disabled"),
    ).toBe(true);
    view.unmount();
    show(false, 12);
    expect(
      screen
        .getByRole("button", {
          name: "Move to instructions",
        })
        .hasAttribute("disabled"),
    ).toBe(true);
  });
  it("keeps facts visible while turning automatic extraction off", () => {
    show();
    fireEvent.click(
      screen.getByRole("switch", { name: "Automatic extraction" }),
    );
    expect(mocks.mutate).toHaveBeenCalledWith(
      { kind: "toggle", enabled: false },
      expect.any(Object),
    );
    expect(screen.getByText("Use API v2")).toBeTruthy();
  });
  it("renders an error instead of an empty memory state", () => {
    mocks.error = true;
    show();
    expect(screen.getByRole("alert").textContent).toContain(
      "Couldn’t load project memory",
    );
    expect(screen.queryByText("Use API v2")).toBeNull();
  });
});
