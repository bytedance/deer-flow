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
const i18n = rs.hoisted(() => ({ locale: "en-US" }));
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
          diagnosticsScope:
            i18n.locale === "zh-CN"
              ? zhCN.settings.skills.diagnosticsScope
              : enUS.settings.skills.diagnosticsScope,
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
import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
  i18n.locale = "en-US";
});

it.each([
  [
    "en-US",
    /Only YAML syntax errors/,
    /Missing frontmatter, metadata validation errors, and unreadable or non-UTF-8 files are not reported/,
    [],
  ],
  [
    "en-US",
    /Only YAML syntax errors/,
    /Missing frontmatter, metadata validation errors, and unreadable or non-UTF-8 files are not reported/,
    [{ package: "broken", path: "SKILL.md", code: "invalid_frontmatter" }],
  ],
  [
    "zh-CN",
    /仅报告.*YAML 语法错误/,
    /不报告缺少头部、元数据校验错误、无法读取或非 UTF-8 编码的文件/,
    [],
  ],
  [
    "zh-CN",
    /仅报告.*YAML 语法错误/,
    /不报告缺少头部、元数据校验错误、无法读取或非 UTF-8 编码的文件/,
    [{ package: "broken", path: "SKILL.md", code: "invalid_frontmatter" }],
  ],
])(
  "explains YAML-only diagnostics and exclusions in %s",
  async (locale, syntax, exclusions, failures) => {
    i18n.locale = locale;
    api.load.mockResolvedValue(failures);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <SkillDiagnostics userId="alice" />
      </QueryClientProvider>,
    );
    await waitFor(() =>
      expect(screen.getByRole<HTMLButtonElement>("button").disabled).toBe(
        false,
      ),
    );
    expect(screen.getByText(syntax)).toBeTruthy();
    expect(screen.getByText(exclusions)).toBeTruthy();
    expect(screen.queryByText("broken/SKILL.md") === null).toBe(
      failures.length === 0,
    );
  },
);

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
