import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const state = rs.hoisted(() => ({
  result: {
    rows: [] as string[][],
    columnCount: 2,
    limited: false,
    unevenRows: false,
  },
  status: "ready",
  retry: rs.fn(),
}));
rs.mock("@/core/artifacts/use-delimited-preview", () => ({
  useDelimitedPreview: () => state,
}));
import { ArtifactTablePreview } from "@/components/workspace/artifacts/artifact-table-preview";
import { I18nProvider } from "@/core/i18n/context";

function mount() {
  return render(
    <I18nProvider initialLocale="en-US">
      <ArtifactTablePreview
        content="fixture"
        delimiter=","
        truncated={false}
        identity="file-1"
      />
    </I18nProvider>,
  );
}
afterEach(cleanup);
beforeEach(() => {
  state.status = "ready";
  state.result = {
    rows: [
      ["ID", "Note"],
      ["00123", "<script>alert(1)</script>"],
    ],
    columnCount: 2,
    limited: false,
    unevenRows: false,
  };
});

describe("ArtifactTablePreview", () => {
  it("preserves literal data and lets the first row become data", () => {
    const { container } = mount();
    expect(screen.getByRole("columnheader", { name: "ID" })).toBeTruthy();
    expect(screen.getByText("00123")).toBeTruthy();
    expect(container.querySelector("script")).toBeNull();
    fireEvent.click(
      screen.getByRole("checkbox", { name: "First row as header" }),
    );
    expect(screen.getByRole("columnheader", { name: "Column 1" })).toBeTruthy();
    expect(screen.getByRole("cell", { name: "ID" })).toBeTruthy();
  });
  it("paginates locally and labels bounded samples honestly", () => {
    state.result.rows = [
      ["ID", "Note"],
      ...Array.from({ length: 202 }, (_, i) => [String(i + 1), "note"]),
    ];
    mount();
    expect(screen.getByText("Preview of first 200 rows")).toBeTruthy();
    expect(screen.getByText("1–50 of preview")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByText("51–100 of preview")).toBeTruthy();
    expect(screen.getByRole("cell", { name: "51" })).toBeTruthy();
    expect(screen.queryByRole("cell", { name: "1" })).toBeNull();
  });
  it("keeps long fields available without enlarging every row", () => {
    const longText = "first line\n" + "x".repeat(200);
    state.result.rows = [
      ["ID", "Note"],
      ["00123", longText],
    ];
    mount();
    fireEvent.click(
      screen.getByRole("button", { name: "View cell: row 1, column 2" }),
    );
    expect(
      screen.getByRole<HTMLTextAreaElement>("textbox", {
        name: "Cell value",
      }).value,
    ).toBe(longText);
  });
  it("offers an explicit retry without displaying stale data on failure", () => {
    state.status = "error";
    mount();
    expect(screen.queryByRole("table")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry preview" }));
    expect(state.retry).toHaveBeenCalled();
  });
});
