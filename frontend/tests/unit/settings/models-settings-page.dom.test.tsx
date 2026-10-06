/**
 * 模型设置页（spec 2026-09-10 §5.7，plan Task 4 seam C）：
 * - 三态：loading / adminRequired(403) / 空态引导；
 * - 列表：来源徽章 + 只读行（config_file）无编辑/删除，UI 行可编辑/删除；
 * - 能力字段在外科式整体写中不丢（改 A 保存后 B 的能力仍在）；
 * - 批量添加：一把 key + 两个 Model ID →「下一步」校验通过 →「添加」save 收到两条 entry 各带同 key；
 * - 全空 Model ID 被阻（save 不被调用）；API 类型仅 openai-compatible 显示。
 */
import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import { ModelsConfigRequestError } from "@/core/models/api";
import type { ManagedModel, ManagedModelInput } from "@/core/models/types";

const fetchMock = rs.hoisted(() => ({ fetch: rs.fn() }));
const hooksMock = rs.hoisted(() => ({
  useModelsConfig: rs.fn(),
  useSaveModelsConfig: rs.fn(),
}));
rs.mock("@/core/api/fetcher", () => ({ fetch: fetchMock.fetch }));
rs.mock("@/core/models/hooks", () => hooksMock);
rs.mock("sonner", () => ({
  toast: { success: rs.fn(), error: rs.fn(), info: rs.fn(), warning: rs.fn() },
}));

const { ModelsSettingsPage } = await import(
  "@/components/workspace/settings/models-settings-page"
);

const M = zhCN.settings.models;

function uiModel(over: Partial<ManagedModel> = {}): ManagedModel {
  return {
    name: "ui-model",
    model: "deepseek-chat",
    display_name: "UI DeepSeek",
    provider: "deepseek",
    endpoint_key: "api_base",
    endpoint: "https://ui.example",
    api_key: "********",
    source: "ui",
    editable: true,
    ...over,
  };
}

function cfgModel(over: Partial<ManagedModel> = {}): ManagedModel {
  return {
    name: "cfg-model",
    model: "gpt-4",
    display_name: null,
    provider: "openai-compatible",
    endpoint_key: "base_url",
    endpoint: null,
    api_key: "********",
    source: "config_file",
    editable: false,
    ...over,
  };
}

const saveMock = rs.fn();

function setConfig(models: ManagedModel[], opts: { loading?: boolean; error?: unknown } = {}) {
  hooksMock.useModelsConfig.mockReturnValue({
    config: { models },
    isLoading: opts.loading ?? false,
    error: opts.error ?? null,
  });
  hooksMock.useSaveModelsConfig.mockReturnValue({ mutate: saveMock, isPending: false });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
        <ModelsSettingsPage />
      </I18nContext.Provider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  saveMock.mockReset();
  fetchMock.fetch.mockReset();
  // Step 1 probes the provider before it unlocks the capability step.
  fetchMock.fetch.mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ ok: true, model_present: true, detail: "available" }),
  } as unknown as Response);
});

afterEach(() => {
  cleanup();
});

describe("ModelsSettingsPage three states", () => {
  it("shows the loading hint", () => {
    setConfig([], { loading: true });
    renderPage();
    expect(screen.getByText(zhCN.common.loading)).toBeDefined();
  });

  it("shows adminRequired on a 403", () => {
    setConfig([], { error: new ModelsConfigRequestError(403, "forbidden") });
    renderPage();
    expect(screen.getByText(M.adminRequired)).toBeDefined();
  });

  it("shows the empty guide with an add button", () => {
    setConfig([]);
    renderPage();
    expect(screen.getByText(M.empty)).toBeDefined();
    expect(screen.getByRole("button", { name: M.add })).toBeDefined();
  });

  it("keeps the add button on the view-switch row, not on a line of its own", () => {
    setConfig([]);
    renderPage();

    // Same parent = same row: the switch is on the left, its action on the right.
    const toggle = screen.getByRole("group", { name: M.viewSwitchLabel });
    expect(screen.getByRole("button", { name: M.add }).parentElement).toBe(
      toggle.parentElement,
    );
  });

  it("gives the view-switch row a floor of its own, so views do not shift it", () => {
    // D5 甲 (spec 2026-09-22 §3.2): the functional view's header ran taller than this line,
    // so switching views moved everything below it by 4px (measured 34/30). The row owns the
    // floor instead of inheriting whatever height its children happen to have.
    setConfig([]);
    renderPage();

    const toggle = screen.getByRole("group", { name: M.viewSwitchLabel });
    expect(toggle.parentElement?.className).toContain("min-h-9");
  });

  it("lets the view-switch row wrap instead of squeezing its controls", () => {
    // D4 甲 (spec 2026-09-24 §3.3): at extreme narrowness the action moves to a second
    // line rather than crushing the switch — one class, the row keeps its own floor.
    setConfig([]);
    renderPage();

    const toggle = screen.getByRole("group", { name: M.viewSwitchLabel });
    expect(toggle.parentElement?.className).toContain("flex-wrap");
  });

  it("renders the add button small, so the row does not outgrow its floor", () => {
    // D5 乙: the default `h-9` would push the row past `min-h-9` and bring the jump back.
    setConfig([]);
    renderPage();

    expect(screen.getByRole("button", { name: M.add }).className).toContain(
      "h-8",
    );
  });

  it("still hides the add action when the admin cannot manage models", () => {
    setConfig([], { error: new ModelsConfigRequestError(403, "forbidden") });
    renderPage();

    // Moving the button up must not offer a wizard that can only fail on save.
    expect(screen.getByText(M.adminRequired)).toBeDefined();
    expect(screen.queryByRole("button", { name: M.add })).toBeNull();
  });

  it("moves the section's prose into the title's ⓘ, both views' sentences together", () => {
    setConfig([]);
    renderPage();

    const F = zhCN.settings.functionalModels;
    // Neither sentence is a line on the page any more (2026-09-16)…
    expect(screen.queryByText(M.description)).toBeNull();
    expect(screen.queryByText(F.description)).toBeNull();
    // …they are one accessible name on the title: the functional view configures this section
    // too, so its sentence belongs here rather than under the view switch.
    expect(
      screen.getByLabelText(`${M.description} ${F.description}`),
    ).toBeDefined();
  });
});

describe("ModelsSettingsPage list", () => {
  it("renders source badges and only lets UI rows be edited/deleted", () => {
    setConfig([uiModel(), cfgModel()]);
    renderPage();

    expect(screen.getByText(M.sourceUi)).toBeDefined();
    expect(screen.getByText(M.sourceConfigFile)).toBeDefined();
    // display_name ?? name
    expect(screen.getByText("UI DeepSeek")).toBeDefined();
    expect(screen.getByText("cfg-model")).toBeDefined();

    expect(screen.getAllByRole("button", { name: M.delete })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: M.edit })).toHaveLength(1);
  });

  it("fills the model rows, so the list stops reading as one grey block", () => {
    setConfig([uiModel(), cfgModel()]);
    renderPage();

    const rows = document.querySelectorAll('[data-slot="item"]');
    expect(rows).toHaveLength(2);
    for (const row of rows) {
      // The settings body and an outlined row resolved to the same colour (2026-09-16);
      // `bg-card` is what the functional view's panels use, so both views share one surface.
      expect(row.className).toContain("bg-card");
    }
  });
});

describe("ModelsSettingsPage capability round trip", () => {
  it("preserves another model's capability fields when saving an edit", async () => {
    setConfig([
      uiModel({
        name: "with-caps",
        supported_context_windows: [200_000, 400_000],
        context_window: 400_000,
        supported_reasoning_efforts: ["low", "medium"],
        reasoning_effort: "medium",
      }),
      uiModel({ name: "no-caps" }),
    ]);
    renderPage();

    // Open the second row's editor and save it untouched: the collection is
    // written wholesale, so the first row's capabilities must survive.
    fireEvent.click(screen.getAllByRole("button", { name: M.edit })[1]!);
    fireEvent.click(screen.getByRole("button", { name: zhCN.common.save }));

    await waitFor(() => expect(saveMock).toHaveBeenCalled());
    const payload = (saveMock.mock.calls[0]?.[0] ?? []) as ManagedModelInput[];
    expect(payload.map((model) => model.name)).toEqual([
      "with-caps",
      "no-caps",
    ]);
    expect(payload[0]).toMatchObject({
      supported_context_windows: [200_000, 400_000],
      context_window: 400_000,
      supported_reasoning_efforts: ["low", "medium"],
      reasoning_effort: "medium",
    });
  });

  it("keeps an untouched anthropic row's effort levels on the same save", async () => {
    // The collection is written wholesale, so an anthropic row the admin never opened is on
    // the wire too. Its declaration is carried through as-is: the level is translated for that
    // protocol at build time, so nothing here needs to strip it.
    setConfig([
      uiModel({
        name: "declared-anthropic",
        provider: "anthropic",
        supports_reasoning_effort: true,
        supported_reasoning_efforts: ["low", "medium", "high"],
        reasoning_effort: "medium",
      }),
      uiModel({ name: "plain" }),
    ]);
    renderPage();

    fireEvent.click(screen.getAllByRole("button", { name: M.edit })[1]!);
    fireEvent.click(screen.getByRole("button", { name: zhCN.common.save }));

    await waitFor(() => expect(saveMock).toHaveBeenCalled());
    const payload = (saveMock.mock.calls[0]?.[0] ?? []) as ManagedModelInput[];
    expect(payload.map((model) => model.name)).toEqual([
      "declared-anthropic",
      "plain",
    ]);
    expect(payload[0]?.supports_reasoning_effort).toBe(true);
    expect(payload[0]?.supported_reasoning_efforts).toEqual([
      "low",
      "medium",
      "high",
    ]);
    expect(payload[0]?.reasoning_effort).toBe("medium");
  });

  it("keeps the five field-parity fields on a row nobody touched", async () => {
    // `toManagedInput` is the projector every *other* row travels through (spec 2026-09-21
    // D6): `default_headers` / the thinking recipes are new, `max_tokens` and
    // `use_responses_api` were already being dropped here. Delete-driven on purpose — the
    // row that must survive is never opened, so no dialog is involved.
    setConfig([
      uiModel({
        name: "with-parity",
        default_headers: { "x-opencode-session": "sess-1" },
        when_thinking_enabled: { extra_body: { thinking: { type: "enabled" } } },
        when_thinking_disabled: {
          extra_body: { thinking: { type: "disabled" } },
        },
        max_tokens: 8192,
        use_responses_api: true,
      }),
      uiModel({ name: "victim" }),
    ]);
    renderPage();

    fireEvent.click(screen.getAllByRole("button", { name: M.delete })[1]!);

    await waitFor(() => expect(saveMock).toHaveBeenCalled());
    const payload = (saveMock.mock.calls[0]?.[0] ?? []) as ManagedModelInput[];
    expect(payload.map((model) => model.name)).toEqual(["with-parity"]);
    expect(payload[0]).toMatchObject({
      default_headers: { "x-opencode-session": "sess-1" },
      when_thinking_enabled: { extra_body: { thinking: { type: "enabled" } } },
      when_thinking_disabled: {
        extra_body: { thinking: { type: "disabled" } },
      },
      max_tokens: 8192,
      use_responses_api: true,
    });
  });
});

describe("ModelsSettingsPage batch add", () => {
  it("expands one key + two model ids into two entries on save", async () => {
    setConfig([]);
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: M.add }));

    fireEvent.change(screen.getByLabelText(M.apiKey), { target: { value: "sk-shared" } });
    fireEvent.change(screen.getByPlaceholderText(M.modelIdPlaceholder), {
      target: { value: "model-a" },
    });
    fireEvent.click(screen.getByRole("button", { name: M.addModelId }));
    const ids = screen.getAllByPlaceholderText(M.modelIdPlaceholder);
    fireEvent.change(ids[1]!, { target: { value: "model-b" } });

    fireEvent.change(screen.getByLabelText(M.endpoint), {
      target: { value: "https://api.example.com/v1" },
    });
    fireEvent.click(screen.getByRole("button", { name: M.next }));
    await waitFor(() => expect(screen.getByRole("button", { name: M.supportedWindows })).toBeDefined());
    fireEvent.click(screen.getByRole("button", { name: M.addSubmit }));

    await waitFor(() => expect(saveMock).toHaveBeenCalled());
    const payload = (saveMock.mock.calls[0]?.[0] ?? []) as ManagedModel[];
    expect(payload).toHaveLength(2);
    expect(payload[0]).toMatchObject({ name: "model-a", api_key: "sk-shared", provider: "openai-compatible" });
    expect(payload[1]).toMatchObject({ name: "model-b", api_key: "sk-shared" });
  });

  it("blocks submit when every model id is empty", async () => {
    setConfig([]);
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: M.add }));
    fireEvent.change(screen.getByLabelText(M.apiKey), { target: { value: "sk-x" } });
    fireEvent.click(screen.getByRole("button", { name: M.next }));

    await waitFor(() => expect(screen.getByText(M.validationNoModelId)).toBeDefined());
    expect(saveMock).not.toHaveBeenCalled();
  });

  it("shows the API type selector for the default openai-compatible provider", () => {
    setConfig([]);
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: M.add }));
    // Default provider is openai-compatible → API type is offered. The
    // "only openai-compatible" rule (hidden for anthropic/deepseek) is pinned
    // at the node level in batch.test.ts (use_responses_api gating); we avoid
    // driving the Radix Select here because its open/close is unreliable under
    // happy-dom.
    expect(screen.getByText(M.apiType)).toBeDefined();
  });
});
