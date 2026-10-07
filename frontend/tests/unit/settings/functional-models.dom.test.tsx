/**
 * 设置 → 模型 的「功能模型」区块（spec 2026-09-10 rag functional-model config §5，plan Task 4 seam C dom）：
 * - 共享模型页内嵌功能模型表单，渲染出各角色的字段；
 * - 已存密钥以掩码回显；未改动 → 保存禁用（空 payload 会把整个 rag_config.json 清空）；
 * - 改动 embedding 模型出现「需重建索引」告警；
 * - 保存 payload 只带「文件已拥有字段带出 + 本次改动」（哨兵保留已存密钥）；
 * - 403 → 拒绝态。
 */
import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import {
  connectivityProbeKey,
  dimensionProbeKey,
  formValuesFromConfig,
  sparseProbeKey,
  sparseServiceProbeKey,
} from "@/core/rag/config-form";
import type { RagConfigView } from "@/core/rag/types";

const ragHooksMock = rs.hoisted(() => ({
  useRagConfig: rs.fn(),
  useSaveRagConfig: rs.fn(),
  useProbeSparseCapability: rs.fn(),
  useProbeSparseService: rs.fn(),
  useProbeDimensions: rs.fn(),
  useProbeConnectivity: rs.fn(),
  useProbeAsrService: rs.fn(),
  useRagMigrationStatus: rs.fn(),
}));
const modelHooksMock = rs.hoisted(() => ({
  useModels: rs.fn(),
  useModelsConfig: rs.fn(),
  useSaveModelsConfig: rs.fn(),
}));
/** Named so a case can prove the RAG save never reaches the model-management mutation. */
const saveModelsMock = rs.hoisted(() => rs.fn());
const knowledgeHooksMock = rs.hoisted(() => ({
  useKnowledgeBases: rs.fn(),
  useReindexStatus: rs.fn(),
  useReindexKnowledgeBase: rs.fn(),
}));
const managementMock = rs.hoisted(() => ({
  loadManagedModels: rs.fn(),
  modelDraft: rs.fn(() => ({})),
  saveManagedModel: rs.fn(),
  testManagedModel: rs.fn(),
}));
const authMock = rs.hoisted(() => ({ useAuth: rs.fn() }));
rs.mock("@/core/rag/hooks", () => ragHooksMock);
rs.mock("@/core/models/hooks", () => ({ ...modelHooksMock, MODELS_QUERY_KEY: ["models"] }));
rs.mock("@/core/models/management", () => managementMock);
rs.mock("@/core/auth/AuthProvider", () => authMock);
rs.mock("@/core/knowledge/hooks", () => knowledgeHooksMock);
rs.mock("sonner", () => ({
  toast: { success: rs.fn(), error: rs.fn(), info: rs.fn(), warning: rs.fn() },
}));

const { RagConfigRequestError } = await import("@/core/rag/api");
const { ModelSettingsPage } = await import(
  "@/components/workspace/settings/model-settings-page"
);

const M = zhCN.settings.models;
const F = zhCN.settings.functionalModels;
const MASKED = "********";
const SPARSE_URL = "http://127.0.0.1:8081";

/** What the server says when it saved the configuration but could not verify it (server-side copy). */
const SAVE_WARNING =
  "提交后的配置已保存，但未能验证：未能连通（EmbedderError）：All connection attempts failed";

/**
 * 重建文案（spec 2026-09-24 §4.3 表）。逐字抄在用例里而不是引用字典：重建现在换的是四类向量
 * （切片 / 实体 / 百科条目 / 人工卡片），源文件与图谱抽取都不重跑，句子必须说全。
 */
const REINDEX_HINT_ZH =
  "更换嵌入提供方或维度后，已有向量全部失效——由此入口重新嵌入：仅重嵌入切片向量。仅读取库中现有文本：不重新解析源文件。";
const REINDEX_CONFIRM_ZH =
  "将重新嵌入该知识库的全部切片向量（不重解析源文件），期间检索结果可能不稳。目标知识库：";
const REINDEX_HINT_EN =
  "Changing the embedding provider or the dimension invalidates every stored vector — re-embed them from this entry: chunk vectors only. Only the library's existing text is read: source files are not re-parsed.";
const REINDEX_CONFIRM_EN =
  "Every chunk vector in this library will be re-embedded (source files are not re-parsed) and retrieval may be unstable while it runs. Target library:";

const saveMock = rs.fn();
const reindexMock = rs.fn();
const probeMock = rs.fn();
const sparseServiceProbeMock = rs.fn();
const dimensionProbeMock = rs.fn();
const connectivityProbeMock = rs.fn();
const asrProbeMock = rs.fn();

/** What the embedding allowlist reports: who can supply the sparse half, and who fixes its own address. */
const EMBEDDING_PROVIDERS = [
  {
    provider_id: "dashscope",
    emits_sparse: true,
    has_fixed_endpoint: true,
    default_endpoint: "https://dashscope.aliyuncs.com",
  },
  {
    provider_id: "volcengine-ark",
    emits_sparse: true,
    has_fixed_endpoint: true,
    default_endpoint: "https://ark.cn-beijing.volces.com",
  },
  {
    provider_id: "openai-compatible",
    emits_sparse: false,
    has_fixed_endpoint: false,
    default_endpoint: null,
  },
];

/** The ASR leg's block (spec 2026-09-28 §3): only the placeholder source travels. */
const ASR_PROVIDERS = [
  { provider_id: "funasr", default_endpoint: null },
  { provider_id: "whisper", default_endpoint: null },
  { provider_id: "openai-audio", default_endpoint: null },
  { provider_id: "dashscope", default_endpoint: "https://dashscope.aliyuncs.com" },
];

/** The rerank allowlist's own block: the same rule, its own shape — no `emits_sparse` there. */
const RERANK_PROVIDERS = [
  {
    provider_id: "dashscope",
    has_fixed_endpoint: true,
    default_endpoint: "https://dashscope.aliyuncs.com",
  },
  {
    provider_id: "generic-rerank",
    has_fixed_endpoint: false,
    default_endpoint: null,
  },
  // TEI fixes no address either (spec 2026-09-24 §4.3). The row matters even though it renders
  // like the fallback: with it, "editable" means the capability block said so, not "unknown
  // provider ⇒ don't take the field away".
  {
    provider_id: "tei-rerank",
    has_fixed_endpoint: false,
    default_endpoint: null,
  },
];

function view(
  over: Partial<RagConfigView["config"]> = {},
  opts: {
    providers?: typeof EMBEDDING_PROVIDERS | null;
    /** Per-field provenance this case needs to restate (e.g. a key that comes from the env). */
    sources?: Record<string, string>;
    /** The save-time probe's verdict (spec 2026-09-17 save-time probe §3 D3). */
    warning?: string | null;
  } = {},
): RagConfigView {
  return {
    // The probe always reports *something*: `null` means it verified the configuration.
    warning: opts.warning ?? null,
    // `null` models a response from a server that predates the capability block — both blocks
    // ship together, so the opt-out drops both (spec 2026-09-17 alignment §3 D3).
    ...(opts.providers === null
      ? {}
      : {
          embedding_providers: opts.providers ?? EMBEDDING_PROVIDERS,
          rerank_providers: RERANK_PROVIDERS,
          asr_providers: ASR_PROVIDERS,
        }),
    config: {
      qdrant_url: "http://qdrant:6333",
      embedding_model: "qwen3.7-text-embedding",
      // Endpoint addresses are required (spec 2026-09-25 rag-endpoint-unlock D3), so the fixture
      // seeds both — the probe keys include them; cases about the empty state pass "".
      embedding_base_url: "http://127.0.0.1:8080/v1",
      embedding_api_key: MASKED,
      rerank_model: "qwen3-rerank",
      rerank_base_url: "http://127.0.0.1:8000",
      rerank_api_key: "",
      vlm_model: "vl-model",
      mineru_api_token: MASKED,
      ...over,
    },
    sources: {
      qdrant_url: "config_file",
      embedding_model: "config_file",
      embedding_api_key: "ui",
      rerank_model: "config_file",
      rerank_api_key: "env",
      vlm_model: "config_file",
      extract_model: "config_file",
      judge_model: "config_file",
      mineru_api_token: "ui",
      // A deployment that has not configured a sparse service has no sparse key anywhere. Stated
      // explicitly: the probes read "unset" to mean "there is nothing to send".
      sparse_api_key: "unset",
      "video.asr_provider": "config_file",
      "video.asr_model": "config_file",
      ...opts.sources,
    },
  };
}

function setRag(
  over: Partial<RagConfigView["config"]> = {},
  opts: {
    loading?: boolean;
    error?: unknown;
    providers?: typeof EMBEDDING_PROVIDERS | null;
    sources?: Record<string, string>;
  } = {},
) {
  // Endpoint addresses are required (spec 2026-09-25 rag-endpoint-unlock D3); the fixture's
  // `view()` seeds both unless a case is about the empty state itself.
  over = { ...over };
  ragHooksMock.useRagConfig.mockReturnValue({
    view: opts.loading
      ? undefined
      : view(over, { providers: opts.providers, sources: opts.sources }),
    isLoading: opts.loading ?? false,
    error: opts.error ?? null,
  });
  ragHooksMock.useSaveRagConfig.mockReturnValue({ mutate: saveMock, isPending: false });
  setMigration();
  // 维度探测与两腿连通点：这些用例不碰它们，保持空闲（结论由各自的行渲染）。
  ragHooksMock.useProbeDimensions.mockReturnValue({
    mutate: dimensionProbeMock,
    data: undefined,
    variables: undefined,
    isPending: false,
  });
  ragHooksMock.useProbeConnectivity.mockReturnValue({
    mutate: connectivityProbeMock,
    data: undefined,
    variables: undefined,
    isPending: false,
  });
  ragHooksMock.useProbeAsrService.mockReturnValue({
    mutate: asrProbeMock,
    data: undefined,
    variables: undefined,
    isPending: false,
  });
  setProbe();
  setSparseServiceProbe();
  setKnowledge();
}

/** 宽度迁移的状态面（spec 2026-09-26 D5-7）：默认"从没跑过"，需要时给一个在飞/已定的结论。 */
function setMigration(
  status: {
    state: "running" | "succeeded" | "failed";
    target_dimension: number;
    detail?: string | null;
    progress?: Record<string, number> | null;
  } | null = null,
) {
  ragHooksMock.useRagMigrationStatus.mockReturnValue({
    data: status ? { detail: null, progress: null, ...status } : undefined,
  });
}

/**
 * The sparse-service probe's stub. Like the capability probe, a verdict only counts for the values
 * it was taken for, so the key is computed the way the view computes it.
 */
function setSparseServiceProbe(
  over: {
    status?: "ok" | "empty" | "unreachable";
    pending?: boolean;
    /** Set to `false` to hand back a verdict taken for other values. */
    keyForCurrentValues?: boolean;
  } = {},
) {
  sparseServiceProbeMock.mockReset();
  const current = formValuesFromConfig(
    view({
      embedding_sparse_source: "external",
      sparse_provider: "tei-sparse",
      sparse_base_url: SPARSE_URL,
    }),
  );
  const stale = formValuesFromConfig(
    view({
      embedding_sparse_source: "external",
      sparse_provider: "tei-sparse",
      sparse_base_url: "http://127.0.0.1:9999",
    }),
  );
  ragHooksMock.useProbeSparseService.mockReturnValue({
    mutate: sparseServiceProbeMock,
    data:
      over.status === undefined
        ? undefined
        : {
            key: sparseServiceProbeKey(
              over.keyForCurrentValues === false ? stale : current,
              false,
            ),
            status: over.status,
          },
    isPending: over.pending ?? false,
  });
}

/**
 * The probe's own stub. Its verdict is bound to the values it was taken for, so the key is
 * computed the same way the view computes it — otherwise "the conclusion belongs to these
 * values" would be asserted against a key the test made up.
 */
function setProbe(
  over: {
    status?: "supported" | "unsupported" | "unverifiable";
    /** Defaults to the key of an untouched dashscope / qwen3.7-text-embedding form. */
    key?: string;
    pending?: boolean;
  } = {},
) {
  probeMock.mockReset();
  ragHooksMock.useProbeSparseCapability.mockReturnValue({
    mutate: probeMock,
    data:
      over.status === undefined
        ? undefined
        : {
            key:
              over.key ??
              sparseProbeKey(
                formValuesFromConfig(
                  view({
                    embedding_provider: "dashscope",
                    embedding_sparse_source: "provider",
                  }),
                ),
              ),
            status: over.status,
            detail: "",
          },
    isPending: over.pending ?? false,
  });
}

/** 重建入口的默认桩：一个库、空闲、未在提交。 */
function setKnowledge(over: { libraries?: Array<{ id: string; name: string }>; status?: unknown; pending?: boolean } = {}) {
  knowledgeHooksMock.useKnowledgeBases.mockReturnValue({
    data: over.libraries ?? [{ id: "kb-1", name: "产品资料" }],
    isLoading: false,
    error: null,
  });
  knowledgeHooksMock.useReindexStatus.mockReturnValue({ data: over.status });
  knowledgeHooksMock.useReindexKnowledgeBase.mockReturnValue({
    mutate: reindexMock,
    isPending: over.pending ?? false,
  });
}

/**
 * Make the next save resolve with the server's verdict: the view's `onSuccess` receives the
 * response body, so this is how a save that *could not be verified* is staged.
 */
function saveWillReturn(warning: string | null) {
  saveMock.mockImplementation(
    (
      _payload: unknown,
      options: { onSuccess?: (saved: RagConfigView) => void },
    ) => options.onSuccess?.(view({}, { warning })),
  );
}

const VL_MODEL = {
  name: "vl-model",
  model: "Qwen/Qwen3-VL-30B",
  display_name: "Qwen3 VL",
  supports_vision: true,
  api_key: "********",
  source: "ui",
  editable: true,
};
const TEXT_MODEL = {
  name: "text-model",
  model: "deepseek-chat",
  display_name: "DeepSeek Chat",
  supports_vision: false,
  api_key: "********",
  source: "ui",
  editable: true,
};
const ANTHROPIC_MODEL = {
  name: "claude-model",
  model: "claude-x",
  display_name: "Claude X",
  supports_vision: true,
  provider: "anthropic",
  api_key: "********",
  source: "ui",
  editable: true,
};

function renderPage(
  models: Array<Record<string, unknown>> = [VL_MODEL, TEXT_MODEL],
) {
  modelHooksMock.useModels.mockReturnValue({
    models: [
      { id: "deepseek-chat", name: "deepseek-chat", model: "deepseek-chat", display_name: "DeepSeek Chat" },
      { id: "qwen-max", name: "qwen-max", model: "qwen-max", display_name: "Qwen Max" },
    ],
    tokenUsageEnabled: false,
    isLoading: false,
    error: null,
  });
  // 共享模型页 + 功能模型区块的目录都来自管理模型查询；条目能力（supports_vision）随行携带。
  const managed = models.map((m, index) => ({
    name: String((m.name as string | undefined) ?? `m-${index}`),
    display_name: (m.display_name as string | undefined) ?? null,
    model: String((m.model as string | undefined) ?? (m.name as string | undefined) ?? `m-${index}`),
    supports_vision: Boolean(m.supports_vision),
    source: "config",
    enabled: true,
    revision: "r1",
    conflict: null,
  }));
  managementMock.loadManagedModels.mockResolvedValue({ models: managed });
  authMock.useAuth.mockReturnValue({ user: { id: "test-user", system_role: "admin" } });

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  // Seed the shared catalogue query synchronously (same key as the page and the
  // view): the pickers must resolve on first paint, not one microtask later.
  client.setQueryData(["managed-models", "test-user"], { models: managed });
  return render(
    <QueryClientProvider client={client}>
      <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
        <ModelSettingsPage />
      </I18nContext.Provider>
    </QueryClientProvider>,
  );
}


beforeEach(() => {
  saveMock.mockReset();
  saveModelsMock.mockReset();
  reindexMock.mockReset();
  dimensionProbeMock.mockReset();
  connectivityProbeMock.mockReset();
  asrProbeMock.mockReset();
  setRag();
});

afterEach(() => {
  cleanup();
});

describe("functional-model form", () => {
  it("shows an effective value and masks a stored key", () => {
    renderPage();

    expect(screen.getByLabelText(F.embeddingModel)).toHaveProperty(
      "value",
      "qwen3.7-text-embedding",
    );
    expect(screen.getByLabelText(F.embeddingApiKey)).toHaveProperty("value", MASKED);
    expect(screen.getByLabelText(F.rerankApiKey)).toHaveProperty("value", "");
    expect(screen.getByText(F.secretFromEnvBadge)).toBeTruthy();
  });

  it("offers the vision-capable entries for the caption picker", () => {
    setRag({ vlm_model: "claude-model" });
    renderPage([VL_MODEL, TEXT_MODEL, ANTHROPIC_MODEL]);

    // The picker is a Radix Select (its open/close is unreliable under happy-dom), so the
    // trigger carries the resolved model name; the option list itself is pinned by
    // visionReferenceOptions in the node suite. The Anthropic entry resolves by its display
    // name like any other caption-capable row.
    expect(screen.getByLabelText(F.captionModel).textContent).toContain("Claude X");
  });

  it("keeps Save disabled until something changes", () => {
    renderPage();

    const save = screen.getByRole("button", { name: zhCN.common.save });
    expect(save).toHaveProperty("disabled", true);

    fireEvent.change(screen.getByLabelText(F.embeddingModel), {
      target: { value: "qwen3.7-text-embedding-v2" },
    });
    expect(screen.getByRole("button", { name: zhCN.common.save })).toHaveProperty("disabled", false);
  });

  it("warns about re-indexing only after the embedding model changes", () => {
    renderPage();

    expect(screen.queryByText(F.embeddingChangeWarning)).toBeNull();

    fireEvent.change(screen.getByLabelText(F.embeddingModel), {
      target: { value: "qwen3.7-text-embedding-v2" },
    });
    expect(screen.getByText(F.embeddingChangeWarning)).toBeTruthy();
  });

  it("submits the carried-forward file fields plus this edit", async () => {
    renderPage();

    fireEvent.change(screen.getByLabelText(F.rerankModel), {
      target: { value: "qwen3-rerank-v2" },
    });
    fireEvent.click(screen.getByRole("button", { name: zhCN.common.save }));

    await waitFor(() => expect(saveMock).toHaveBeenCalled());
    expect(saveMock.mock.calls[0]?.[0]).toEqual({
      rerank_model: "qwen3-rerank-v2",
      // The file already owns these two secrets: re-submitted as sentinels so they survive.
      embedding_api_key: MASKED,
      mineru_api_token: MASKED,
      // The provider selects have no empty state — their ids come from the backend allowlist —
      // so an untouched row submits the *effective* default explicitly (config-form.test.ts
      // pins that; 2026-09-14 provider dimension).
      embedding_provider: "dashscope",
      embedding_sparse_source: "provider",
      rerank_provider: "dashscope",
      parse_provider: "mineru-cloud",
    });
  });

  it("shows the denial state for a non-admin", () => {
    setRag({}, { error: new RagConfigRequestError(403, "forbidden") });
    renderPage();

    expect(screen.getByText(M.adminRequired)).toBeTruthy();
    expect(screen.queryByLabelText(F.embeddingModel)).toBeNull();
  });
});

/**
 * The RAG default row (spec 2026-09-23 default model D4/D5).
 *
 * The copy is frozen by D5 and asserted here against the real locale files; the candidate
 * catalogue and the none/unknown-value handling are pinned in the view's own dom file, and
 * the payload semantics (`{}` vs `{key: ""}`) in the node suite. What is left for this file
 * is where the row lives, that its field joins the *existing* save, and that a failed save
 * does not roll the draft back.
 */
describe("RAG default row", () => {
  it("appears in the functional view as the sole control of its kind", () => {
    renderPage();

    // Exactly one: the section title carries no second control (D4). The view is
    // mounted inline on this page (Task 6 挂载), so the row is present from the start.
    expect(screen.getAllByLabelText(F.defaultModel).length).toBe(1);
    expect(screen.getByText(F.defaultModel)).toBeTruthy();
    // The explanation rides the row's ⓘ, like every other explanatory sentence here.
    expect(screen.getByLabelText(F.defaultModelHint)).toBeTruthy();
  });

  it("states the D3 fallback where the roles are explained", () => {
    // D5's alignment rule: a role's hint says what an empty value means now — the UI
    // override goes away first, the RAG default only takes over when the merged role is
    // still empty. The old "or the configured primary model" claim predates that.
    for (const hint of [F.captionModelHint]) {
      expect(hint).toContain(F.defaultModel);
      expect(hint).not.toContain("主模型");
      expect(hint).not.toContain("primary model");
    }
  });

  it("ships D5's copy verbatim in both locales", () => {
    // The row's three strings are frozen by the spec's D5 table; hard-coding them here is
    // what makes an edit to either locale file visible as a test failure.
    expect(F.defaultModel).toBe("RAG 默认模型");
    expect(F.defaultModelNone).toBe("（使用配置默认）");
    expect(F.defaultModelHint).toBe(
      "用于图片配文未单独指定模型时的选择，不影响聊天主模型及其他功能；此项留空时使用配置中的 RAG 默认，配置也未指定则使用模型列表第一项。",
    );

    const FE = enUS.settings.functionalModels;
    expect(FE.defaultModel).toBe("RAG default model");
    expect(FE.defaultModelNone).toBe("(config default)");
    expect(FE.defaultModelHint).toBe(
      "Used when image captioning has no separate model selection. It does not affect chat models or other features. Leave this unset to inherit the configured RAG default, or the first model in the list if none is configured.",
    );
  });

  it("carries the file's own default into the RAG payload, never a model catalogue", async () => {
    setRag(
      { default_model: "qwen-max" },
      { sources: { default_model: "ui" } },
    );
    renderPage();

    // The row itself is untouched; editing another field is what makes the save reachable.
    fireEvent.change(screen.getByLabelText(F.rerankModel), {
      target: { value: "qwen3-rerank-v2" },
    });
    fireEvent.click(screen.getByRole("button", { name: zhCN.common.save }));

    await waitFor(() => expect(saveMock).toHaveBeenCalled());
    const payload = saveMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(payload.default_model).toBe("qwen-max");
    expect(payload).not.toHaveProperty("models");
    // The model catalogue has its own endpoint and its own save; the RAG save must not touch it.
    expect(saveModelsMock).not.toHaveBeenCalled();
  });

  it("keeps the draft when the save never succeeds", () => {
    setRag({ default_model: "qwen-max" }, { sources: { default_model: "ui" } });
    renderPage();

    fireEvent.change(screen.getByLabelText(F.rerankModel), {
      target: { value: "qwen3-rerank-v2" },
    });
    fireEvent.click(screen.getByRole("button", { name: zhCN.common.save }));

    // Nothing in the view resets the form on a save attempt: a rejected write leaves the
    // admin's edits in place (the failure itself surfaces as the hook's toast, not in here).
    expect(screen.getByLabelText(F.rerankModel)).toHaveProperty(
      "value",
      "qwen3-rerank-v2",
    );
    expect(
      screen.getByRole("button", { name: zhCN.common.save }),
    ).toHaveProperty("disabled", false);
  });
});

/**
 * The save-time probe's verdict (spec 2026-09-17 save-time probe §3 D3). A 400 is the ordinary
 * failure path and already reaches the user as a toast; what has no other home is the *successful*
 * save the server could not verify — it must not read as a clean save, and it must not read as a
 * refusal either.
 */
describe("thinking follow-chat menu (spec 2026-10-03 D1=甲)", () => {
  // One dropdown under the RAG default row. Its five rows are the five *role slots* — a
  // model in two slots is two rows — each showing the model its slot points at. The trigger
  // names itself (no label in front) and carries the state at its tail (his UI rule).
  // Radix DropdownMenu opens on keydown in jsdom, not on click (三点菜单先例). Its modal
  // layer aria-hides the rest of the page while open, so out-of-menu queries need `hidden`.
  const trigger = () =>
    screen.getByRole("button", { name: F.thinkingMenuLabel, hidden: true });
  const openMenu = () => fireEvent.keyDown(trigger(), { key: "ArrowDown" });
  const saveButton = () =>
    screen.getByRole<HTMLButtonElement>("button", {
      name: zhCN.common.save,
      hidden: true,
    });

  it("names itself in the trigger with the state at the tail, and no label in front", () => {
    renderPage();

    // The label exists only as the trigger's aria-label; the visible text is the state.
    expect(screen.queryAllByText(F.thinkingMenuLabel)).toHaveLength(0);
    expect(trigger().textContent).toContain("未选择");
  });

  it("ships the trigger copy verbatim in both locales", () => {
    expect(F.thinkingMenuLabel).toBe("思考跟随对话模型");
    expect(F.thinkingMenuState(0)).toBe("思考跟随对话模型（未选择）");
    expect(F.thinkingMenuState(3)).toBe("思考跟随对话模型（已选 3 项）");

    const FE = enUS.settings.functionalModels;
    expect(FE.thinkingMenuLabel).toBe("Thinking follows the chat model");
    expect(FE.thinkingMenuState(0)).toBe(
      "Thinking follows the chat model (none selected)",
    );
    expect(FE.thinkingMenuState(2)).toBe(
      "Thinking follows the chat model (2 selected)",
    );
  });

  it("lists the role slot with the model it points at", async () => {
    renderPage();

    openMenu();
    const items = await screen.findAllByRole("menuitemcheckbox");

    // The row is a role slot, and it carries two cells that share the menu's subgrid, so
    // the model name lines up as one column (2026-10-06); the composite "role · model"
    // read survives as the row's aria-label, which the by-name queries below rely on.
    const cells = (item: HTMLElement) =>
      [
        ...item.querySelectorAll(
          '[data-slot="thinking-role"], [data-slot="thinking-model"]',
        ),
      ].map((cell) => cell.textContent);
    expect(items.map(cells)).toEqual([[F.captionModel, "vl-model"]]);
  });

  it("keeps the menu open across picks and counts them in the trigger", async () => {
    renderPage();

    openMenu();
    fireEvent.click(
      await screen.findByRole("menuitemcheckbox", {
        name: `${F.captionModel} · vl-model`,
      }),
    );

    // A pick must not close the menu on the admin.
    expect(
      screen.getByRole("menuitemcheckbox", {
        name: `${F.captionModel} · vl-model`,
      }),
    ).toBeTruthy();
    expect(trigger().textContent).toContain("已选 1 项");
    expect(saveButton().disabled).toBe(false);
  });

  it("submits the toggles through the RAG save, and nothing for the untouched legs", async () => {
    renderPage();

    openMenu();
    fireEvent.click(
      await screen.findByRole("menuitemcheckbox", {
        name: `${F.captionModel} · vl-model`,
      }),
    );
    fireEvent.click(saveButton());

    await waitFor(() => expect(saveMock).toHaveBeenCalled());
    // The fixture's other file-owned fields ride along; what this edit owns is the one toggle.
    const payload = saveMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(payload.vlm_thinking).toBe(true);
  });

  it("seeds a stored true as checked, and an uncheck is submitted as false", async () => {
    setRag({ vlm_thinking: true });
    renderPage();

    expect(trigger().textContent).toContain("已选 1 项");

    openMenu();
    fireEvent.click(
      await screen.findByRole("menuitemcheckbox", {
        name: `${F.captionModel} · vl-model`,
      }),
    );
    fireEvent.click(saveButton());

    await waitFor(() => expect(saveMock).toHaveBeenCalled());
    // `false`, not an omitted key: the whole-object PUT would read an omission as "keep it".
    const payload = saveMock.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(payload.vlm_thinking).toBe(false);
    expect(trigger().textContent).toContain("未选择");
  });
});

describe("save-time verification notice", () => {
  it("shows what the server could not verify about the configuration it saved", async () => {
    renderPage();
    saveWillReturn(SAVE_WARNING);

    fireEvent.change(screen.getByLabelText(F.rerankModel), {
      target: { value: "qwen3-rerank-v2" },
    });
    fireEvent.click(screen.getByRole("button", { name: zhCN.common.save }));

    const notice = await screen.findByText(SAVE_WARNING);
    // Saved, with a caveat — the write went through, so the notice is a status and not an alert.
    expect(saveMock).toHaveBeenCalledTimes(1);
    expect(notice.getAttribute("role")).toBe("status");
  });

  it("says nothing once the server verified a save", async () => {
    renderPage();
    saveWillReturn(SAVE_WARNING);

    fireEvent.change(screen.getByLabelText(F.rerankModel), {
      target: { value: "qwen3-rerank-v2" },
    });
    fireEvent.click(screen.getByRole("button", { name: zhCN.common.save }));
    await screen.findByText(SAVE_WARNING);

    // The notice belongs to the save it describes; the next save reports its own verdict.
    saveWillReturn(null);
    fireEvent.change(screen.getByLabelText(F.rerankModel), {
      target: { value: "qwen3-rerank-v3" },
    });
    fireEvent.click(screen.getByRole("button", { name: zhCN.common.save }));

    await waitFor(() => expect(screen.queryByText(SAVE_WARNING)).toBeNull());
  });
});

describe("functional-model layout", () => {
  it("groups the fields under described sections", () => {
    renderPage();

    for (const title of [
      F.groupRetrieval,
      F.groupMultimodal,
      F.groupServices,
    ]) {
      expect(screen.getByText(title)).toBeTruthy();
    }
    expect(screen.getByLabelText(F.groupRetrievalHint)).toBeTruthy();
    expect(screen.getByLabelText(F.groupMultimodalHint)).toBeTruthy();
    expect(screen.getByLabelText(F.groupServicesHint)).toBeTruthy();
  });

  it("leaves no provider-fixed lock copy on the endpoint rows", () => {
    // Spec 2026-09-25 rag-endpoint-unlock §4.7/§5: the unlock is endpoint-only — other locked
    // rows keep their own reason copies (their lock is about the *mode*, not a vendor address).
    renderPage();

    expect(screen.getByLabelText(F.embeddingBaseUrl)).toBeTruthy();
    expect(screen.getByLabelText(F.rerankBaseUrl)).toBeTruthy();
    expect(screen.queryByText("由提供方固定")).toBeNull();
  });

  it("writes the retrieval pair's row labels once, not once per column", () => {
    renderPage();

    // The two roles share one label gutter (2026-09-15): each of the pair's four rows is
    // labelled a single time **in the wide layout** — below `lg` every value cell carries its
    // own copy of the label as a stacking line head (spec 2026-09-24 §3.2), hidden above `lg`.
    // Scoped to the retrieval card: 「模型」 is also the section's own title.
    const card = screen
      .getByText(F.groupRetrieval)
      .closest<HTMLElement>('[data-slot="card"]')!;
    const counts = [
      F.providerLabel,
      F.modelLabel,
      F.apiKeyLabel,
      F.endpointLabel,
    ].map((shared) => [
      shared,
      within(card)
        .getAllByText(shared)
        .filter((el) => !el.closest(".md\\:hidden")).length,
    ]);
    expect(Object.fromEntries(counts)).toEqual({
      [F.providerLabel]: 1,
      [F.modelLabel]: 1,
      [F.apiKeyLabel]: 1,
      [F.endpointLabel]: 1,
    });
    expect(screen.getByLabelText(F.embeddingApiKey)).toBeTruthy();
    expect(screen.getByLabelText(F.rerankApiKey)).toBeTruthy();
  });

  it("puts the provenance chip inside the credential field, not beside it", () => {
    renderPage();

    // The fixture backs the rerank key from the environment, so that row carries the chip.
    const input = screen.getByLabelText(F.rerankApiKey);
    const chip = screen.getByText(F.secretFromEnvBadge);

    // One wrapper holds both, so the chip spends the field's own padding instead of the
    // row's width — the retrieval pair has two fields on that row (2026-09-16).
    expect(input.parentElement).toBe(chip.parentElement);
    expect(input.className).toContain("pl-32");
    // It is a label on the field, never a click target: the caret must still land on the input.
    expect(chip.className).toContain("pointer-events-none");
  });

  it("treats the chip as a placeholder: it clears the moment the field is yours", () => {
    renderPage();

    const input = screen.getByLabelText(F.rerankApiKey);
    expect(screen.getByText(F.secretFromEnvBadge)).toBeTruthy();
    expect(input.className).toContain("pl-32");

    // Focusing already means "this field is mine": the caret must not start after the note.
    fireEvent.focus(input);
    expect(screen.queryByText(F.secretFromEnvBadge)).toBeNull();
    expect(input.className).not.toContain("pl-32");

    // Left empty again, the note is back — it is state, not a one-shot hint.
    fireEvent.blur(input);
    expect(screen.getByText(F.secretFromEnvBadge)).toBeTruthy();

    // And once something is typed it stays away on blur: the override is what the field holds,
    // so the note must never re-appear in front of it (2026-09-16).
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "sk-mine" } });
    fireEvent.blur(input);
    expect(screen.queryByText(F.secretFromEnvBadge)).toBeNull();
  });

  it("paints a credential chip and a locked row's reason identically", () => {
    renderPage();

    // Two cells that both say "you do not type this here", so they read the same: same size,
    // same tint, and both lead their field. They used to differ in all three (2026-09-16).
    // Re-pointed at the parse rows: the endpoint rows are plain inputs now
    // (spec 2026-09-25 rag-endpoint-unlock), while these still say *why* they
    // are locked (the field belongs to the other parse mode).
    const chip = screen.getByText(F.secretFromEnvBadge);
    const reason = screen.getAllByText(F.lockedLocalOnly)[0]!;

    for (const element of [chip, reason]) {
      expect(element.className).toContain("text-sm");
      expect(element.className).toContain("text-muted-foreground/70");
    }
    expect(chip.className).toContain("left-3");
  });

  it("labels every input, including the ones that used to be bare boxes", () => {
    renderPage();

    for (const label of [F.apiKeyLabel, F.modelLabel, F.qdrantUrl, F.mineruToken]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(screen.getByLabelText(F.embeddingApiKey)).toBeTruthy();
  });

  it("picks the caption model from the configured entries, asking for no endpoint or key", () => {
    renderPage();

    const captionRow = screen.getByLabelText(F.captionModel).closest("div");

    expect(screen.getByLabelText(F.captionModel).textContent).toContain("Qwen3 VL");
    // The endpoint and the key come from that entry, so the row has no inputs at all.
    expect(captionRow?.querySelector("input")).toBeNull();
    expect(screen.getByLabelText(F.captionModelHint)).toBeTruthy();
  });

  it("does not claim an Anthropic entry can never serve this leg", () => {
    // The old sentence is what made the picker hide those entries; both locales drop it.
    expect(F.captionModelHint).not.toContain("Anthropic 条目无法用于这条腿");
    expect(enUS.settings.functionalModels.captionModelHint).not.toContain(
      "Anthropic entry can never serve this leg",
    );
    // Anchors, so deleting the sentence would fail too: the row still says where the
    // endpoint and key come from, and that the protocol follows the entry.
    expect(F.captionModelHint).toContain("接口地址与 API Key");
    expect(F.captionModelHint).toContain("Anthropic");
    expect(enUS.settings.functionalModels.captionModelHint).toContain(
      "endpoint and API key",
    );
    expect(enUS.settings.functionalModels.captionModelHint).toContain(
      "Anthropic",
    );
  });

  it("stops warning about a missing vision model when an Anthropic entry can serve the leg", () => {
    renderPage([ANTHROPIC_MODEL, TEXT_MODEL]);

    // The old filter left this picker with no vision-capable entry at all, and the row said so.
    expect(screen.queryByText(F.vlmNoVisionModel)).toBeNull();
  });

  it("still warns when no entry declares vision support", () => {
    renderPage([TEXT_MODEL]);

    expect(screen.getByText(F.vlmNoVisionModel)).toBeTruthy();
  });

  it("keeps a stored caption model that names no configured entry", () => {
    setRag({ vlm_model: "qwen3.7-flash-legacy" });
    renderPage();

    expect(screen.getByLabelText(F.captionModel).textContent).toContain(
      "qwen3.7-flash-legacy",
    );
  });
});

/**
 * 接口地址行（spec 2026-09-25 rag-endpoint-unlock）：永远可编辑——同一家厂商可能有不同地址
 * （百炼 workspace 级端点）；「恢复默认」与"厂商固定"的锁都退役；厂商默认只作灰字占位
 * （不落值、不回落）；地址必填（缺 ⇒ Save 禁用 + 一句话原因）。
 */
describe("embedding address row", () => {
  const saveButton = () =>
    screen.getByRole<HTMLButtonElement>("button", { name: zhCN.common.save });
  const resetButton = () =>
    screen.queryByRole("button", { name: "恢复默认" });

  it("offers the Ark dialect and saves it without a dense-only complaint", () => {
    setRag({
      embedding_provider: "volcengine-ark",
      embedding_sparse_source: "provider",
      embedding_base_url: "https://ark.cn-beijing.volces.com",
      rerank_base_url: "https://dashscope.aliyuncs.com",
    });
    renderPage();

    // It emits both halves, so the "dense only" refusal must not fire for it.
    expect(screen.queryByRole("alert")).toBeNull();
    // An ordinary edit still has to unlock Save — proof the rule is not just "nothing changed".
    fireEvent.change(screen.getByLabelText(F.embeddingModel), {
      target: { value: "doubao-embedding-vision-250615" },
    });
    expect(saveButton().disabled).toBe(false);
  });

  it("keeps the row editable even for a provider that fixes its own endpoint", () => {
    setRag({
      embedding_provider: "volcengine-ark",
      embedding_base_url: "",
      rerank_base_url: "",
    });
    renderPage();

    const input = screen.getByLabelText<HTMLInputElement>(F.embeddingBaseUrl);
    // The vendor default is only the grey hint — never the value.
    expect(
      screen.getByPlaceholderText("https://ark.cn-beijing.volces.com"),
    ).toBeTruthy();
    expect(input.value).toBe("");
    expect(resetButton()).toBeNull();
  });

  it("keeps a stored override editable and offers no reset", () => {
    setRag({
      embedding_provider: "volcengine-ark",
      embedding_base_url: "https://ws-example.cn-beijing.maas.aliyuncs.com",
    });
    renderPage();

    const input = screen.getByLabelText<HTMLInputElement>(F.embeddingBaseUrl);
    expect(input.value).toBe(
      "https://ws-example.cn-beijing.maas.aliyuncs.com",
    );
    expect(resetButton()).toBeNull();
  });

  it("shows the example placeholder for a provider without a default endpoint", () => {
    setRag({
      embedding_provider: "openai-compatible",
      embedding_base_url: "http://127.0.0.1:8080/v1",
    });
    renderPage();

    expect(screen.getByLabelText(F.embeddingBaseUrl)).toBeTruthy();
    expect(screen.getByPlaceholderText("https://api.example.com/v1")).toBeTruthy();
    expect(resetButton()).toBeNull();
  });

  it("blocks Save while either endpoint is empty and says why", () => {
    setRag({
      embedding_provider: "volcengine-ark",
      embedding_base_url: "",
      rerank_base_url: "https://dashscope.aliyuncs.com",
    });
    renderPage();

    expect(saveButton().disabled).toBe(true);
    expect(screen.getByText("请填写接口地址")).toBeTruthy();

    fireEvent.change(screen.getByLabelText(F.embeddingBaseUrl), {
      target: { value: "https://ark.cn-beijing.volces.com" },
    });
    expect(saveButton().disabled).toBe(false);
    expect(screen.queryByText("请填写接口地址")).toBeNull();
  });
});

/**
 * 重排地址那一行与嵌入那行**同构**（spec 2026-09-25 rag-endpoint-unlock）：同样永远可编辑、
 * 无「恢复默认」、默认端点只作灰字占位。存量 `rerank_base_url` 在运行期仍然优先。
 */
describe("rerank address row", () => {
  const resetButton = () =>
    screen.queryByRole("button", { name: "恢复默认" });

  it("keeps the row editable and hints the vendor default", () => {
    setRag({ rerank_provider: "dashscope", rerank_base_url: "" });
    renderPage();

    const input = screen.getByLabelText<HTMLInputElement>(F.rerankBaseUrl);
    expect(input).toBeTruthy();
    // Both legs share the same default endpoint as their hint; the hint is not a value.
    expect(
      screen.getAllByPlaceholderText("https://dashscope.aliyuncs.com").length,
    ).toBe(2);
    expect(screen.queryAllByText("https://dashscope.aliyuncs.com").length).toBe(
      0,
    );
    expect(resetButton()).toBeNull();
  });

  it("keeps a stored rerank override editable and offers no reset", () => {
    setRag({
      rerank_provider: "dashscope",
      rerank_base_url: "http://127.0.0.1:9999",
    });
    renderPage();

    const input = screen.getByLabelText<HTMLInputElement>(F.rerankBaseUrl);
    expect(input.value).toBe("http://127.0.0.1:9999");
    expect(resetButton()).toBeNull();
  });

  it("stays editable when the server sends no rerank capability block", () => {
    // `unknown ≠ cannot`：旧的网关答不了这个问题，就不要替它把框锁上（占位退 example.com）。
    setRag({ rerank_provider: "dashscope" }, { providers: null });
    renderPage();

    expect(screen.getByLabelText(F.rerankBaseUrl)).toBeTruthy();
    expect(
      screen.getAllByPlaceholderText("https://api.example.com/v1").length,
    ).toBe(2);
  });
});

/**
 * 重排的第三种形状 TEI（spec 2026-09-24 §4.3）：下拉多一格，端点行照旧按能力块判；模型行
 * 不加任何条件提示（同日已裁——请求里不带 model 字段这件事由既有 `sparseModelHint` 先例覆盖）。
 */
describe("TEI rerank provider", () => {
  it("offers the TEI shape as a third rerank provider", async () => {
    renderPage();

    fireEvent.click(screen.getByRole("combobox", { name: F.rerankProvider }));

    // 三项，顺序即形状的次序；「通用重排」的标签同时瘦身——TEI 不再算进它的形状里。
    const options = await screen.findAllByRole("option");
    expect(options.map((option) => option.textContent?.trim())).toEqual([
      "阿里百炼 (DashScope)",
      "通用重排 (Cohere / Jina 形状)",
      "TEI 重排",
    ]);
    expect(enUS.settings.functionalModels.providerTeiRerank).toBe("TEI rerank");
    expect(enUS.settings.functionalModels.providerGenericRerank).toBe(
      "Generic rerank (Cohere / Jina shape)",
    );
  });

  it("keeps the address row editable for a stored TEI provider", () => {
    // 存量的 `tei-rerank` 要活过载入归一（`asEnum` 与渲染共用同一个选项常量，spec §4.3 ⚠️）：
    // 漏加一格就会被静默读成 dashscope，端点行随即锁死、存量地址再也改不动。
    setRag({ rerank_provider: "tei-rerank" });
    renderPage();

    expect(screen.getByLabelText(F.rerankBaseUrl)).toBeTruthy();
    expect(screen.getByLabelText(F.rerankModel)).toBeTruthy();
  });
});

/**
 * 稀疏来源与所选嵌入提供商的能力不匹配（spec 2026-09-16 §3 D2）：编辑期就地拦下，
 * 而不是等第一次入库/检索时后端拒绝。文案与后端那句同一事实，且 Save 旁也要给出原因——
 * 只灰按钮不给理由，告警落在视口外的人会卡在「能改不能存、不知道为什么」。
 */
describe("sparse source vs provider capability", () => {
  const unsupported = () =>
    setRag({
      embedding_provider: "openai-compatible",
      embedding_sparse_source: "provider",
    });
  const saveButton = () =>
    screen.getByRole<HTMLButtonElement>("button", { name: zhCN.common.save });

  it("refuses a dense-only provider that is asked for the sparse half", () => {
    unsupported();
    renderPage();

    expect(screen.getByRole("alert").textContent).toBe(
      F.sparseProviderUnsupported,
    );
    // An ordinary edit would normally make Save clickable; this pair has to keep it blocked,
    // which is what makes the assertion below about the rule and not about "nothing changed".
    fireEvent.change(screen.getByLabelText(F.embeddingModel), {
      target: { value: "bge-m3" },
    });
    expect(saveButton().disabled).toBe(true);
    // The same sentence rides next to the button it blocks.
    expect(saveButton().parentElement?.textContent).toContain(
      F.sparseProviderUnsupported,
    );
  });

  it("lets the save through once the sparse source no longer needs the provider", () => {
    setRag({
      embedding_provider: "openai-compatible",
      embedding_sparse_source: "bm25",
    });
    renderPage();

    expect(screen.queryByRole("alert")).toBeNull();
    expect(saveButton().disabled).toBe(true); // nothing edited yet — the usual rule
    fireEvent.change(screen.getByLabelText(F.embeddingModel), {
      target: { value: "bge-m3" },
    });
    expect(saveButton().disabled).toBe(false);
  });

  it("stays quiet when the server reports no capabilities at all", () => {
    setRag(
      {
        embedding_provider: "openai-compatible",
        embedding_sparse_source: "provider",
      },
      { providers: null },
    );
    renderPage();

    // An older server cannot answer the question, so it must not be answered for it.
    expect(screen.queryByRole("alert")).toBeNull();
    expect(saveButton().disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(F.embeddingModel), {
      target: { value: "bge-m3" },
    });
    expect(saveButton().disabled).toBe(false);
  });
});

/**
 * 模型级能力探测（spec 2026-09-16 §3 D2/D4）：名单说得清「provider 这个方言支不支持」，
 * 说不清「这个具体模型支不支持」——于是选中后就打一次真实调用（只读、不落盘），
 * 三态里只有 `unsupported` 拦人；`unverifiable` 放行并标「未验证」，因为"没查成"不是"不支持"。
 */
describe("sparse capability probe", () => {
  const saveButton = () =>
    screen.getByRole<HTMLButtonElement>("button", { name: zhCN.common.save });
  /** An edit that would otherwise unlock Save without touching what the probe was asked about. */
  const editUnrelated = () =>
    fireEvent.change(screen.getByLabelText(F.rerankModel), {
      target: { value: "qwen3-rerank-v2" },
    });
  const editModel = () =>
    fireEvent.change(screen.getByLabelText(F.embeddingModel), {
      target: { value: "bge-m3" },
    });
  /** The advanced disclosure is closed — and unmounted — until it is opened. */
  const openAdvanced = () =>
    fireEvent.click(screen.getByRole("button", { name: /^高级设置/ }));

  it("blocks a model the probe proved cannot supply the sparse half", () => {
    setProbe({ status: "unsupported" });
    renderPage();

    expect(screen.getByRole("alert").textContent).toBe(
      F.sparseProviderUnsupported,
    );
    // An ordinary edit would normally make Save clickable; this verdict has to keep it blocked,
    // which is what makes the assertion below about the rule and not about "nothing changed".
    editUnrelated();
    expect(saveButton().disabled).toBe(true);
    expect(saveButton().parentElement?.textContent).toContain(
      F.sparseProviderUnsupported,
    );
  });

  it("drops that verdict the moment the model it was taken for changes", () => {
    setProbe({ status: "unsupported" });
    renderPage();

    expect(screen.getByRole("alert").textContent).toBe(
      F.sparseProviderUnsupported,
    );
    // A different model is a different question: answering it with the old verdict would let a
    // just-refused candidate through (or refuse one nobody has checked).
    editModel();
    expect(screen.queryByText(F.sparseProviderUnsupported)).toBeNull();
    expect(saveButton().disabled).toBe(false);
  });

  it("keeps the admin's own choice of sparse source untouched", () => {
    setProbe({ status: "unsupported" });
    renderPage();
    openAdvanced();

    // Not silently rewritten to an easier value: showing one thing and sending another is
    // worse than the refusal, and the admin loses the right to know what was chosen.
    expect(
      screen.getByLabelText(F.embeddingSparseSource).textContent,
    ).toContain(F.sparseSourceProvider);
  });

  it("lets an unverifiable model through, marked as unverified", () => {
    setProbe({ status: "unverifiable" });
    renderPage();
    openAdvanced();

    expect(screen.getByText(F.sparseUnverified)).toBeTruthy();
    // Same slot as 检测中, so the row keeps its height when the verdict lands.
    expect(
      screen
        .getByText(F.sparseUnverified)
        .closest('[data-slot="select-trigger"]'),
    ).not.toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    editUnrelated();
    expect(saveButton().disabled).toBe(false);
  });

  it("says nothing extra when the probe confirmed the model", () => {
    setProbe({ status: "supported" });
    renderPage();
    openAdvanced();

    expect(screen.queryByText(F.sparseUnverified)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
    editUnrelated();
    expect(saveButton().disabled).toBe(false);
  });

  it("shows the probe as in flight while it is running", () => {
    setProbe({ pending: true });
    renderPage();
    openAdvanced();

    expect(screen.getByText(F.sparseProbing)).toBeTruthy();
    // Nothing is claimed while the answer is unknown — and nothing is blocked either.
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the probe mark inside the field, so the row never grows", () => {
    setProbe({ pending: true });
    renderPage();
    openAdvanced();

    const mark = screen.getByText(F.sparseProbing);
    // The trigger is a fixed-height box, so a mark that rides in it cannot push the rows below it
    // down and back — which is what a line of its own did, on every open and every model edit.
    expect(mark.closest('[data-slot="select-trigger"]')).not.toBeNull();
    // …and it is a *sibling* of the value slot, never inside it: Radix mirrors the selected item's
    // text into the trigger, so anything placed in the value would be copied into the options.
    expect(mark.closest('[data-slot="select-value"]')).toBeNull();
  });

  it("does not ask the server until the question can be asked at all", async () => {
    setRag({
      embedding_provider: "dashscope",
      embedding_sparse_source: "provider",
      embedding_model: "",
    });
    renderPage();

    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(probeMock).not.toHaveBeenCalled();
  });

  it("does not ask when the sparse half is coming from somewhere else", async () => {
    setRag({
      embedding_provider: "dashscope",
      embedding_sparse_source: "bm25",
    });
    renderPage();

    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(probeMock).not.toHaveBeenCalled();
  });

  it("asks even though the key arrives from the environment", async () => {
    // The deployed shape: a stored-or-environment key comes back as an empty input box with
    // `sources[key] === "env"`. Reading "the box is empty" as "no key" would make the whole
    // feature dead precisely where it is needed.
    setRag(
      {
        embedding_provider: "dashscope",
        embedding_sparse_source: "provider",
        embedding_api_key: "",
      },
      { sources: { embedding_api_key: "env" } },
    );
    renderPage();

    expect(
      screen.getByLabelText<HTMLInputElement>(F.embeddingApiKey).value,
    ).toBe("");
    await waitFor(() => expect(probeMock).toHaveBeenCalled(), {
      timeout: 2000,
    });
    expect(probeMock.mock.calls[0]?.[0]).toMatchObject({
      embedding_provider: "dashscope",
      embedding_model: "qwen3.7-text-embedding",
    });
  });
});

/**
 * 「稀疏模型」这一行的交代（spec 2026-09-16 §3 D6）：值会落盘，但**从不发给服务**——TEI 一个
 * 实例只服务一个模型，所以请求里没有 model 字段。本期只补说明、不改行为（字段照存、下发照旧）。
 */
describe("sparse model disclosure", () => {
  it("says the sparse model is stored but never sent", () => {
    setRag({ embedding_sparse_source: "external" });
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /^高级设置/ }));

    expect(screen.getByLabelText(F.sparseModelHint)).toBeTruthy();
    // The sentence has to name the reason, not merely exist: "does this field do anything?" is the
    // question the row raises, and one TEI instance serving one model is the answer.
    expect(F.sparseModelHint).toContain("TEI");
    expect(F.sparseModelHint).toContain("一个实例只服务一个模型");
  });
});

/**
 * 外部稀疏服务的连通性探针（spec 2026-09-16 connectivity §3 D4）：地址填错 / 服务没起这类问题
 * 过去要等入库才暴露，现在在编辑期就报。**只报不拦**——服务可能稍后才起，把"暂时连不上"升格成
 * "不许保存"就是 `unverifiable` 那条教训的重演。
 */
describe("sparse service connectivity", () => {
  const withExternal = (over: Record<string, unknown> = {}) =>
    setRag({
      embedding_sparse_source: "external",
      sparse_provider: "tei-sparse",
      sparse_base_url: SPARSE_URL,
      ...over,
    });
  const saveButton = () =>
    screen.getByRole<HTMLButtonElement>("button", { name: zhCN.common.save });
  /** The advanced disclosure is closed — and unmounted — until it is opened. */
  const openAdvanced = () =>
    fireEvent.click(screen.getByRole("button", { name: /^高级设置/ }));

  it("asks the service once the address is there", async () => {
    withExternal();
    renderPage();
    openAdvanced();

    await waitFor(() => expect(sparseServiceProbeMock).toHaveBeenCalled(), {
      timeout: 2000,
    });
    expect(sparseServiceProbeMock.mock.calls[0]?.[0]).toMatchObject({
      sparse_provider: "tei-sparse",
      sparse_base_url: SPARSE_URL,
    });
  });

  it("does not ask at all without an address to reach", async () => {
    withExternal({ sparse_base_url: "" });
    renderPage();
    openAdvanced();

    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(sparseServiceProbeMock).not.toHaveBeenCalled();
  });

  it("does not ask while the sparse half comes from somewhere else", async () => {
    setRag({ embedding_sparse_source: "bm25" });
    renderPage();
    openAdvanced();

    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(sparseServiceProbeMock).not.toHaveBeenCalled();
  });

  it("warns that the service is unreachable, and still lets the admin save", () => {
    // The stub has to come *after* the config stub: seeding the view re-registers it.
    withExternal();
    setSparseServiceProbe({ status: "unreachable" });
    renderPage();
    openAdvanced();

    // The address row says so in place…
    expect(screen.getByText(F.sparseServiceUnreachable)).toBeTruthy();
    // …and the save is *not* blocked: the service may come up in a minute.
    fireEvent.change(screen.getByLabelText(F.rerankModel), {
      target: { value: "qwen3-rerank-v2" },
    });
    expect(saveButton().disabled).toBe(false);
  });

  it("warns differently when the service answers with no terms at all", () => {
    withExternal();
    setSparseServiceProbe({ status: "empty" });
    renderPage();
    openAdvanced();

    // Reachable but useless is a different problem from unreachable: the admin should look at the
    // model it loaded, not at the network.
    expect(screen.getByText(F.sparseServiceEmpty)).toBeTruthy();
    expect(screen.queryByText(F.sparseServiceUnreachable)).toBeNull();
  });

  it("says nothing when the service answered with terms", () => {
    withExternal();
    setSparseServiceProbe({ status: "ok" });
    renderPage();
    openAdvanced();

    expect(screen.queryByText(F.sparseServiceUnreachable)).toBeNull();
    expect(screen.queryByText(F.sparseServiceEmpty)).toBeNull();
  });

  it("drops a verdict taken for another address", () => {
    withExternal();
    setSparseServiceProbe({
      status: "unreachable",
      keyForCurrentValues: false,
    });
    renderPage();
    openAdvanced();

    // Editing the address asks a new question; answering it with the old verdict would report a
    // service that was never called.
    expect(screen.queryByText(F.sparseServiceUnreachable)).toBeNull();
  });

  it("keeps the mark inside the address field", () => {
    withExternal();
    setSparseServiceProbe({ status: "unreachable" });
    renderPage();
    openAdvanced();

    const mark = screen.getByText(F.sparseServiceUnreachable);
    expect(mark.closest('[data-slot="sparse-service-status"]')).not.toBeNull();
  });
});

/**
 * 「独立稀疏服务」但没挑提供商（2026-09-17 补）：这一对后端**必定拒绝**，而界面上原来既不提示、
 * 也能保存——要等那一次 400 才知道。现在与 dense-only 那条走同一套表现：告警 + Save 旁同一句 +
 * Save 禁用；同时把那个空选项的措辞从"（由服务决定）"（那是解析档位那行的语义）改成「（未选择）」。
 */
describe("sparse service with no provider chosen", () => {
  const saveButton = () =>
    screen.getByRole<HTMLButtonElement>("button", { name: zhCN.common.save });
  const openAdvanced = () =>
    fireEvent.click(screen.getByRole("button", { name: /^高级设置/ }));

  it("says so while editing, and keeps Save blocked", () => {
    // The wire says "not declared" with null; the form widens it to "" for Radix.
    setRag({ embedding_sparse_source: "external", sparse_provider: null });
    renderPage();
    openAdvanced();

    expect(screen.getByRole("alert").textContent).toBe(
      F.sparseServiceUnconfigured,
    );
    // An ordinary edit would normally unlock Save; this pair has to keep it blocked.
    fireEvent.change(screen.getByLabelText(F.rerankModel), {
      target: { value: "qwen3-rerank-v2" },
    });
    expect(saveButton().disabled).toBe(true);
    expect(saveButton().parentElement?.textContent).toContain(
      F.sparseServiceUnconfigured,
    );
  });

  it("lets the save through once a provider is chosen", () => {
    setRag({
      embedding_sparse_source: "external",
      sparse_provider: "tei-sparse",
      sparse_base_url: SPARSE_URL,
    });
    renderPage();
    openAdvanced();

    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.change(screen.getByLabelText(F.rerankModel), {
      target: { value: "qwen3-rerank-v2" },
    });
    expect(saveButton().disabled).toBe(false);
  });

  it("calls the empty option what it is, not what the parse row means", () => {
    // The wire says "not declared" with null; the form widens it to "" for Radix.
    setRag({ embedding_sparse_source: "external", sparse_provider: null });
    renderPage();
    openAdvanced();

    // The label is only reachable inside the listbox (Radix does not open in happy-dom), so pin it
    // through the trigger's mirrored value — which is where the misleading wording used to show.
    expect(screen.getByLabelText(F.sparseProvider).textContent).toContain(
      F.sparseProviderNone,
    );
  });
});

/**
 * 重建入口（spec 2026-09-14 §5 / P4）：设置页本身没有知识库身份，所以目标库由这一行
 * 选出来，再经确认弹窗点名——重建会把目标库的全部切片重新嵌入，点错代价高。
 */
describe("rebuild entry", () => {
  it("keeps the action disabled until a library is chosen", () => {
    renderPage();

    const action = screen.getByRole<HTMLButtonElement>("button", {
      name: F.reindexAction,
    });
    expect(action.disabled).toBe(true);
    // 目标未定时不撒谎：连「上次重建完成」这类历史结论也不必显示（这里本来就没有）
    expect(screen.queryByText(F.reindexLastFailed)).toBeNull();
  });

  it("says there is nothing to rebuild when the user owns no library", () => {
    setRag();
    setKnowledge({ libraries: [] });
    renderPage();

    expect(screen.getByText(F.reindexNoKb)).toBeTruthy();
    expect(screen.getByRole<HTMLButtonElement>("button", { name: F.reindexAction }).disabled).toBe(true);
  });

  it("renders live counters while a rebuild runs and disables the action", () => {
    setRag();
    setKnowledge({
      status: {
        in_progress: true,
        last_run: null,
        progress: {
          documents_total: 7,
          documents_done: 3,
          chunks_indexed: 42,
        },
      },
    });
    renderPage();

    const status = screen.getByRole("status");
    expect(status.textContent).toContain("3/7");
    expect(status.textContent).toContain("42");
    expect(screen.getByRole<HTMLButtonElement>("button", { name: F.reindexAction }).disabled).toBe(true);
  });

  it("counts the chunk vectors in the running line", () => {
    setRag();
    setKnowledge({
      status: {
        in_progress: true,
        last_run: null,
        progress: {
          documents_total: 3,
          documents_done: 3,
          chunks_indexed: 100,
        },
      },
    });
    renderPage();

    // 切片重建只重嵌入切片向量（重嵌入三件 = 切片一类）：行里的计数就是 chunks_indexed。
    const status = screen.getByRole("status");
    expect(status.textContent).toContain("3/3");
    expect(status.textContent).toContain("已写入向量 100");
  });

  it("spells out that a rebuild moves every vector collection", () => {
    renderPage();

    // ⓘ 的可及名就是那句话本身，所以钉住它等于同时钉住"文案对"与"它真的挂在页面上"。
    expect(screen.getByLabelText(REINDEX_HINT_ZH)).toBeTruthy();
    // 确认句与 en 两侧没有 DOM 可钉（本套件只渲染 zh-CN），逐字对字典。
    expect(F.reindexConfirmDescription).toBe(REINDEX_CONFIRM_ZH);
    expect(enUS.settings.functionalModels.reindexHint).toBe(REINDEX_HINT_EN);
    expect(enUS.settings.functionalModels.reindexConfirmDescription).toBe(
      REINDEX_CONFIRM_EN,
    );
  });

  it("reports the previous run's verdict when idle", () => {
    setRag();
    setKnowledge({ status: { in_progress: false, last_run: "failed", progress: null } });
    renderPage();

    expect(screen.getByRole("alert").textContent).toContain(F.reindexLastFailed);
  });
});

/** 确认弹窗单独测：不驱动 Radix，直接渲染它自己的契约（点名目标 + 确认/禁用）。 */
describe("ReindexDialog", () => {
  it("names the target library and confirms", async () => {
    const { ReindexDialog } = await import(
      "@/components/workspace/settings/reindex-dialog"
    );
    const onConfirm = rs.fn();
    render(
      <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
        <ReindexDialog
          open
          onOpenChange={() => undefined}
          kbName="产品资料"
          onConfirm={onConfirm}
          pending={false}
        />
      </I18nContext.Provider>,
    );

    // 目标必须点名：设置页没有库身份，确认框是最后一道「点错库」的防线
    expect(screen.getByText(F.reindexConfirmTitle)).toBeTruthy();
    expect(screen.getByText("产品资料")).toBeTruthy();
    // 范围也要点名（spec 2026-09-24 §4.3）：换的是四类向量，不只是切片。
    expect(screen.getByText(REINDEX_CONFIRM_ZH)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: F.reindexConfirmAction }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("blocks a second confirm while the request is in flight", async () => {
    const { ReindexDialog } = await import(
      "@/components/workspace/settings/reindex-dialog"
    );
    render(
      <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
        <ReindexDialog
          open
          onOpenChange={() => undefined}
          kbName="产品资料"
          onConfirm={rs.fn()}
          pending
        />
      </I18nContext.Provider>,
    );

    expect(
      screen.getByRole<HTMLButtonElement>("button", {
        name: F.reindexConfirmAction,
      }).disabled,
    ).toBe(true);
  });
});

/** The connectivity probe's stub: one leg's verdict, bound to the same key the view computes. */
function setConnectivityProbe(
  over: {
    leg?: "embedding" | "rerank";
    status?: "ok" | "refused" | "unreachable" | "dimension_unavailable" | "half_missing";
    detail?: string;
  } = {},
) {
  ragHooksMock.useProbeConnectivity.mockReturnValue({
    mutate: connectivityProbeMock,
    data:
      over.status === undefined
        ? undefined
        : {
            key: connectivityProbeKey(over.leg ?? "embedding", formValuesFromConfig(view()), true),
            status: over.status,
            detail: over.detail ?? "probe detail",
            measured_dimension: null,
          },
    variables: undefined,
    isPending: false,
  });
}

/**
 * The dimension probe's stub: like its siblings, a verdict only counts for the values it was
 * taken for — the key is computed the way the view computes it. Call **after** `setRag`.
 */
function setDimensionProbe(
  over: {
    status?: "ok" | "unreachable";
    type?: "tiered" | "range" | "fixed" | null;
    native?: number | null;
    values?: number[];
    candidates?: number[];
  } = {},
) {
  ragHooksMock.useProbeDimensions.mockReturnValue({
    mutate: dimensionProbeMock,
    data:
      over.status === undefined
        ? undefined
        : {
            key: dimensionProbeKey(formValuesFromConfig(view())),
            status: over.status,
            type: over.type ?? null,
            native: over.native ?? null,
            values: over.values ?? [],
            candidates: over.candidates ?? [],
            detail: "probe detail",
          },
    variables: undefined,
    isPending: false,
  });
}

describe("维度行 + 两标题连通点 (spec 2026-09-26 §3 / D5-5)", () => {
  /** 高级设置默认收起；探测行就在里面。 */
  const openAdvanced = () => fireEvent.click(screen.getByRole("button", { name: /^高级设置/ }));

  it("keeps the in-field chevron to the page's own select style", () => {
    // 标准 SelectTrigger 的箭头是 `size-4 opacity-50`，距右 12px（触发器的 px-3）。框内那处
    // （维度行）曾经是 `size-3.5` + `pr-1.5` ⇒ 视觉上小一号、也贴得更靠边（2026-09-29 他报的
    // 缺陷）。ASR 模型行已随视频腿裁掉，只剩维度行一处。几何只能在真浏览器量，这里钉住规格本身。
    setDimensionProbe({ status: "ok", type: "tiered", native: 1024, values: [256, 1024] });
    renderPage();
    openAdvanced();

    const button = document.querySelector<HTMLElement>('[data-slot="dimension-tiers-trigger"]');
    expect(button, "dimension-tiers-trigger").toBeTruthy();
    expect(button!.querySelector("svg")!.getAttribute("class")).toContain("size-4");
    expect(button!.querySelector("svg")!.getAttribute("class")).toContain("opacity-50");
    // 12px 的右内边距 = 标准触发器的 px-3。
    expect(button!.parentElement!.className).toContain("pr-3");
  });

  it("puts the dimension row at the head of the advanced panel — editable, button-free", () => {
    renderPage();
    openAdvanced();

    const row = document.querySelector<HTMLElement>('[data-slot="dimension-row"]')!;
    expect(row).toBeTruthy();
    expect(row.parentElement!.firstElementChild).toBe(row);

    const input = within(row).getByLabelText<HTMLInputElement>(F.dimensionLabel);
    expect(input.readOnly).toBe(false);
    // 没有「探测」按钮：探测是自动的，档位（有结论时）才是芯片。行内唯一的按钮是 ⓘ
    // （它的 aria-label 就是那句提示，见 D5-4）。
    const buttons = within(row).queryAllByRole("button");
    expect(buttons).toHaveLength(1);
    expect(buttons[0]!.getAttribute("aria-label")).toBe(
      `${F.dimensionHint} ${F.dimensionProbeHint}`,
    );

    fireEvent.change(input, { target: { value: "1536" } });
    expect(input.value).toBe("1536");
  });

  it("keeps the detected tiers in an in-field dropdown and fills the input from one", async () => {
    // 档位不再平铺在行里（那会让这一项变成两行）：收进输入框右侧的小箭头，点开是下拉菜单。
    setDimensionProbe({ status: "ok", type: "tiered", native: 1024, values: [256, 1024] });
    renderPage();
    openAdvanced();

    const control = document.querySelector<HTMLElement>('[data-slot="dimension-control"]')!;
    expect(control.querySelector('[data-slot="dimension-chips"]')).toBeNull();

    fireEvent.pointerDown(within(control).getByRole("button", { name: F.dimensionTierHint }));
    const items = await screen.findAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual(["256", "1024"]);
    expect(screen.getByText(F.dimensionNativeHint(1024))).toBeTruthy();

    fireEvent.click(items[0]!);
    expect(screen.getByLabelText<HTMLInputElement>(F.dimensionLabel).value).toBe("256");
  });

  it("shows the single value of a fixed-width model in the read-only first line", () => {
    // ③ 型不吃参数：只有一个可取值。行必须把它**填进去**（不是只当占位提示）——
    // 否则留空=1024，一个原生 768 的模型永远保存不过，而用户没有输入口。
    setDimensionProbe({ status: "ok", type: "fixed", native: 768, values: [768] });
    renderPage();
    openAdvanced();

    const input = screen.getByLabelText<HTMLInputElement>(F.dimensionLabel);
    expect(input.readOnly).toBe(true);
    expect(input.value).toBe("768");
    // 没有可选项 ⇒ 没有下拉箭头；为什么只读由行内的 ⓘ 说明（"不接受维度参数"那句）。
    expect(document.querySelector('[data-slot="dimension-tiers-trigger"]')).toBeNull();
    const info = screen.getByRole<HTMLButtonElement>("button", {
      name: new RegExp(F.dimensionHint),
    });
    expect(info.getAttribute("aria-label")).toContain(F.dimensionFixedHint(768));
  });

  it("reports the no-tier case through the in-field status dot, never an empty list", () => {
    setDimensionProbe({ status: "ok", type: "tiered", native: 768, values: [] });
    renderPage();
    openAdvanced();

    const dot = document.querySelector<HTMLElement>('[data-slot="dimension-status"]')!;
    expect(dot.getAttribute("data-state")).toBe("no-tiers");
    expect(dot.getAttribute("aria-label")).toBe(F.dimensionNoTiers);
    // 没有档位就没有下拉箭头（不渲染空列表），手填照旧。
    expect(document.querySelector('[data-slot="dimension-tiers-trigger"]')).toBeNull();
    expect(screen.getByLabelText<HTMLInputElement>(F.dimensionLabel).readOnly).toBe(false);
  });

  it("offers the candidate widths below the native one for a range model", async () => {
    setDimensionProbe({
      status: "ok",
      type: "range",
      native: 1024,
      values: [1024],
      candidates: [256, 512, 768, 1024, 1536],
    });
    renderPage();
    openAdvanced();

    fireEvent.pointerDown(
      screen.getByRole("button", { name: F.dimensionTierHint }),
    );
    const items = await screen.findAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual(["256", "512", "768", "1024"]);
    expect(screen.getByText(F.dimensionNativeHint(1024))).toBeTruthy();
  });

  it("reports 未探明 in-field and offers no tier list when the probe could not answer", () => {
    setDimensionProbe({ status: "unreachable" });
    renderPage();
    openAdvanced();

    const dot = document.querySelector<HTMLElement>('[data-slot="dimension-status"]')!;
    expect(dot.getAttribute("data-state")).toBe("unprobed");
    expect(dot.getAttribute("aria-label")).toContain(F.dimensionUnprobed);
    expect(document.querySelector('[data-slot="dimension-tiers-trigger"]')).toBeNull();
  });

  it("turns both role headings into connectivity buttons, and a ready leg asks the server", () => {
    setRag({}, { sources: { embedding_api_key: "env" } });
    renderPage();

    // 锚定「<角色> · 」：LegHeading 的可及名是这个形状；组 ⓘ 的 aria 是整句提示
    // （2026-09-30 起含「向量模型/重排模型」），不锚定会先命中 ⓘ。
    const heading = screen.getByRole<HTMLButtonElement>("button", {
      name: new RegExp(`^${F.embeddingModel} ·`),
    });
    expect(heading.getAttribute("data-slot")).toBe("leg-heading");
    expect(heading.getAttribute("data-state")).toBe("untested");
    expect(heading.querySelector('[data-slot="leg-dot"]')).toBeTruthy();
    expect(heading.disabled).toBe(false);

    fireEvent.click(heading);
    expect(connectivityProbeMock).toHaveBeenCalledTimes(1);
    expect(connectivityProbeMock.mock.calls[0]![0]).toMatchObject({
      leg: "embedding",
      provider: "dashscope",
    });

    // 重排腿同日就位，且它那发不带维度（spec §3）。
    const rerank = screen.getByRole("button", {
      name: new RegExp(`^${F.rerankModel} ·`),
    });
    expect(rerank.getAttribute("data-slot")).toBe("leg-heading");
  });

  it("keeps the dots disabled until the leg's own coordinates are complete", () => {
    setRag({}, { sources: { embedding_api_key: "unset" } });
    renderPage();

    const heading = screen.getByRole("button", {
      name: new RegExp(`^${F.embeddingModel} ·`),
    });
    expect(
      screen.getByRole<HTMLButtonElement>("button", {
        name: new RegExp(`^${F.embeddingModel} ·`),
      }).disabled,
    ).toBe(true);
    expect(heading.getAttribute("data-state")).toBe("untested");
    fireEvent.click(heading);
    expect(connectivityProbeMock).not.toHaveBeenCalled();
  });

  it("raises the embedding-change warning when the width moves, and drops it when put back", () => {
    renderPage();
    openAdvanced();

    const input = screen.getByLabelText<HTMLInputElement>(F.dimensionLabel);
    const seeded = input.value;
    expect(screen.queryByText(F.embeddingChangeWarning)).toBeNull();

    fireEvent.change(input, { target: { value: "1536" } });
    expect(screen.queryByText(F.embeddingChangeWarning)).toBeTruthy();

    // 填回原值 ⇒ 不再是改动（D5-4 的"同值不触发"）。
    fireEvent.change(input, { target: { value: seeded } });
    expect(screen.queryByText(F.embeddingChangeWarning)).toBeNull();
  });
  it("probes the dimension automatically once the coordinates are complete", async () => {
    setRag({}, { sources: { embedding_api_key: "env" } });
    renderPage();

    // 不用点任何按钮：坐标齐了、防抖过后自己发一发（spec §3 探测的触发）。
    await waitFor(() => expect(dimensionProbeMock).toHaveBeenCalledTimes(1));
    expect(dimensionProbeMock.mock.calls[0]![0]).toMatchObject({
      embedding_provider: "dashscope",
    });
  });

  it("paints the dot green when reachable and amber when it is not (橙是他定的)", () => {
    setRag({}, { sources: { embedding_api_key: "env" } });
    setConnectivityProbe({ status: "unreachable" });
    renderPage();

    const bad = screen.getByRole<HTMLButtonElement>("button", {
      name: new RegExp(`^${F.embeddingModel} ·`),
    });
    expect(bad.getAttribute("data-state")).toBe("bad");
    expect(bad.querySelector('[data-slot="leg-dot"]')!.className).toContain("bg-amber-500");
  });

  it("keeps both legs' own verdicts — probing one never greys the other", () => {
    // 结论是「按腿」的。早期两条腿共用一个 mutation 实例 ⇒ 只留最后一发：点一条变绿，
    // 另一条（哪怕刚测过绿）当场退回灰。两个 hook 实例各自持有自己的结论。
    // 桩按调用次序一前一后发（该组件两次调用 = 两条腿；StrictMode 下每轮重放同样的次序），
    // 旧实现每次渲染只调一次 ⇒ 第二条腿拿不到自己的结论，本用例即红。
    setRag({}, { sources: { embedding_api_key: "env", rerank_api_key: "env" } });
    const form = formValuesFromConfig(view());
    const verdictFor = (leg: "embedding" | "rerank") => ({
      mutate: connectivityProbeMock,
      data: {
        key: connectivityProbeKey(leg, form, true),
        status: "ok" as const,
        detail: "连通正常",
        measured_dimension: null,
      },
      variables: undefined,
      isPending: false,
    });
    let call = 0;
    ragHooksMock.useProbeConnectivity.mockImplementation(() =>
      call++ % 2 === 0 ? verdictFor("embedding") : verdictFor("rerank"),
    );

    renderPage();

    // 锚定「<角色> ·」的理由同上：组 ⓘ 的提示语里含角色名。
    const dotOf = (label: string) =>
      screen
        .getByRole<HTMLButtonElement>("button", {
          name: new RegExp(`^${label} ·`),
        })
        .querySelector('[data-slot="leg-dot"]')!;
    expect(dotOf(F.embeddingModel).className).toContain("bg-emerald-500");
    expect(dotOf(F.rerankModel).className).toContain("bg-emerald-500");
  });

  it("puts a leg's reason in the house tooltip, not in a native title", () => {
    // 原生 `title` 会弹出浏览器自己画的白框，与仓库的深色 Tooltip 不合（2026-09-28 他报回）。
    setRag({}, { sources: { embedding_api_key: "env" } });
    renderPage();

    const heading = screen.getByRole<HTMLButtonElement>("button", {
      name: new RegExp(`^${F.embeddingModel} ·`),
    });
    expect(heading.hasAttribute("title")).toBe(false);
    // 那句原因仍在无障碍名里（提示气泡的内容就是它）。
    expect(heading.getAttribute("aria-label")).toBe(
      `${F.embeddingModel} · ${F.legDotUntested}`,
    );
    // 灰点的悬浮要说"点它能做什么"（spec D5-5 的"hover：为什么灰、点它可以测"），
    // 不只是报个状态词。
    expect(F.legDotUntested).toContain("点");
  });

  it("gives a promised-but-missing sparse half its own reason, still amber", () => {
    // 双路 provider 答了稠密、稀疏为空：连得上、凭据对、宽度也对 —— 这是一种"答案"，
    // 不该被说成"连不上"（它与「要不到该维度」同族，颜色仍是橙、理由各写各的）。
    setRag({}, { sources: { embedding_api_key: "env" } });
    setConnectivityProbe({
      status: "half_missing",
      detail:
        "连得上，但这个模型没给稀疏那一半：嵌入 provider 返回了空的稀疏向量 ⇒ 请改为「独立稀疏服务」或「本地 BM25」",
    });
    renderPage();

    const head = screen.getByRole<HTMLButtonElement>("button", {
      name: new RegExp(`^${F.embeddingModel} ·`),
    });
    expect(head.getAttribute("data-state")).toBe("bad-half");
    expect(head.querySelector('[data-slot="leg-dot"]')!.className).toContain("bg-amber-500");
    expect(head.getAttribute("aria-label")).toContain("没给稀疏那一半");
  });

  it("keeps a reachable leg green", () => {
    setRag({}, { sources: { embedding_api_key: "env" } });
    setConnectivityProbe({ status: "ok" });
    renderPage();

    const ok = screen.getByRole<HTMLButtonElement>("button", {
      name: new RegExp(`^${F.embeddingModel} ·`),
    });
    expect(ok.getAttribute("data-state")).toBe("ok");
    expect(ok.querySelector('[data-slot="leg-dot"]')!.className).toContain("bg-emerald-500");
  });
});


describe("宽度迁移：保存前的确认 + 在飞状态面 (spec 2026-09-26 D5-7)", () => {
  const openAdvanced = () =>
    fireEvent.click(screen.getByRole("button", { name: /^高级设置/ }));

  /** 维度的输入框住在高级设置里；改它 = 触发迁移的那一次保存。 */
  function changeDimension(value: string) {
    openAdvanced();
    fireEvent.change(screen.getByLabelText(F.dimensionLabel), {
      target: { value },
    });
  }

  it("asks before a width change instead of saving straight away", async () => {
    renderPage();
    changeDimension("1536");

    fireEvent.click(screen.getByRole("button", { name: zhCN.common.save }));

    // 还没保存：先问。对话框给的是"这么做会重建全库"这件事本身。
    expect(saveMock).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(F.dimensionConfirmTitle)).toBeTruthy();
    expect(within(dialog).getByText(F.dimensionConfirmDescription)).toBeTruthy();

    fireEvent.click(
      within(dialog).getByRole("button", { name: F.dimensionConfirmAction }),
    );
    await waitFor(() => expect(saveMock).toHaveBeenCalledTimes(1));
    expect(saveMock.mock.calls[0]?.[0]).toMatchObject({ embedding_dimension: 1536 });
  });

  it("still saves without asking when the width is not what changed", async () => {
    renderPage();

    fireEvent.change(screen.getByLabelText(F.rerankModel), {
      target: { value: "qwen3-rerank-v2" },
    });
    fireEvent.click(screen.getByRole("button", { name: zhCN.common.save }));

    await waitFor(() => expect(saveMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("treats typing the width already in force as no change", async () => {
    renderPage();
    changeDimension("1024");

    fireEvent.click(screen.getByRole("button", { name: zhCN.common.save }));

    await waitFor(() => expect(saveMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("reports the running migration and blocks a second save until it settles", () => {
    setMigration({
      state: "running",
      target_dimension: 1536,
      progress: { kbs_done: 1, kbs_total: 2 },
    });
    renderPage();
    changeDimension("1536");

    const line = document.querySelector('[data-slot="migration-status"]')!;
    expect(line.textContent).toContain(F.migrationRunning);
    expect(line.textContent).toContain("1/2");
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: zhCN.common.save })
        .disabled,
    ).toBe(true);
  });

  it("reports how a settled migration ended", () => {
    setMigration({ state: "succeeded", target_dimension: 1536 });
    renderPage();

    expect(
      document.querySelector('[data-slot="migration-status"]')!.textContent,
    ).toBe(F.migrationSucceeded);
  });

  it("says why a failed migration left the width alone", () => {
    setMigration({
      state: "failed",
      target_dimension: 1536,
      detail: "RuntimeError: 向量库连不上",
    });
    renderPage();

    const line = document.querySelector('[data-slot="migration-status"]')!;
    expect(line.textContent).toContain(F.migrationFailed);
    expect(line.textContent).toContain("向量库连不上");
  });
});

