import { afterEach, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const api = rs.hoisted(() => ({ load: rs.fn(), reload: rs.fn() }));
rs.mock("@/core/skills/api", () => ({
  loadSkillDiagnostics: api.load,
  reloadSkills: api.reload,
}));
rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      common: { loading: "Loading" },
      settings: {
        skills: {
          diagnosticsTitle: "Could not load",
          diagnosticsScope: "Your custom skills only",
          diagnosticsInvalid: "Invalid YAML",
          diagnosticsQuote: "Quote colon values",
          diagnosticsRefresh: "Reload skills",
          diagnosticsRefreshing: "Reloading skills",
          diagnosticsFailed: "Could not load diagnostics",
          diagnosticsReloadFailed: "Could not reload skills",
        },
      },
    },
  }),
}));

import { SkillDiagnostics } from "@/components/workspace/capabilities/skill-diagnostics";

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

it("keeps warnings on reload failure, then refetches both lists after success", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  client.setQueryData(["skills"], ["existing"]);
  api.load.mockResolvedValue([
    {
      package: "broken",
      path: "SKILL.md",
      code: "invalid_frontmatter",
      hint: "quote_colon_value",
      line: 3,
      column: 27,
    },
  ]);
  api.reload.mockRejectedValueOnce(new Error("offline"));
  render(
    <QueryClientProvider client={client}>
      <SkillDiagnostics userId="alice" />
    </QueryClientProvider>,
  );
  await screen.findByText("broken/SKILL.md:3:27");
  expect(screen.getByText("Quote colon values")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Reload skills" }));
  await screen.findByRole("alert");
  expect(screen.getByText("broken/SKILL.md:3:27")).toBeTruthy();
  expect(client.getQueryState(["skills"])?.isInvalidated).toBe(false);
  let finish!: () => void;
  api.reload.mockImplementationOnce(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  api.load.mockResolvedValue([]);
  fireEvent.click(screen.getByRole("button", { name: "Reload skills" }));
  await waitFor(() =>
    expect(
      screen.getByRole<HTMLButtonElement>("button", {
        name: "Reloading skills",
      }).disabled,
    ).toBe(true),
  );
  expect(screen.getByText("broken/SKILL.md:3:27")).toBeTruthy();
  await act(async () => finish());
  await waitFor(() =>
    expect(screen.queryByText("broken/SKILL.md:3:27")).toBeNull(),
  );
  expect(client.getQueryState(["skills"])?.isInvalidated).toBe(true);
});

it("does not display a colon hint for generic YAML failures", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  api.load.mockResolvedValue([
    { package: "broken", path: "SKILL.md", code: "invalid_frontmatter" },
  ]);
  render(
    <QueryClientProvider client={client}>
      <SkillDiagnostics userId="bob" />
    </QueryClientProvider>,
  );
  await screen.findByText("broken/SKILL.md");
  expect(screen.getByText("Invalid YAML")).toBeTruthy();
  expect(screen.queryByText("Quote colon values")).toBeNull();
});
