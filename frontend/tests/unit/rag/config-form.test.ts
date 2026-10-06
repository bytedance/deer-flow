/**
 * RAG 功能模型配置的前端纯逻辑（spec 2026-09-10 rag functional-model config §5，plan Task 3 seam C node）：
 * - `formValuesFromConfig`：GET 视图 → 表单初值（已存密钥以哨兵回显）；
 * - `buildRagConfigInput`：表单 → PUT payload。后端是**整对象替换**，故 payload 必须由
 *   「文件已拥有的字段带出 + 本次改动」两部分组成——否则只改一个字段会把文件里其它覆盖值删掉；
 * - `isEmbeddingChange`：换 embedding 模型的判定（驱动「已有知识库需重建索引」告警）；
 * - 客户端：GET/PUT 的 URL/方法/body 与 403 → isAdminRequired 的错误映射。
 *
 * fixture 刻意让「文件默认什么都不拥有」（全部 config_file / env / unset），每条用例自己声明
 * 哪几个字段属于文件（`sources` 里标 `ui`），这样 payload 期望值是可逐条读懂的。
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";

const fetchMock = rs.hoisted(() => ({ fetch: rs.fn() }));
rs.mock("@/core/api/fetcher", () => ({ fetch: fetchMock.fetch }));

const { MASKED_RAG_SECRET, loadRagConfig, RagConfigRequestError, saveRagConfig } =
  await import("@/core/rag/api");
import {
  ASR_MODEL_MENU,
  asrModelForProviderSwitch,
  buildRagConfigInput,
  changesEmbeddingDimension,
  connectivityProbeKey,
  dimensionProbeKey,
  EMBEDDING_PROVIDER_OPTIONS,
  formValuesFromConfig,
  hasFormChanges,
  isCaptionCapable,
  isEmbeddingChange,
  isSparseProviderOptionDisabled,
  isSparseServiceUnconfigured,
  isSparseSourceUnsupported,
  MODEL_REFERENCE_NONE,
  modelReferenceOptions,
  PARSE_TIER_OPTIONS,
  ENDPOINT_PLACEHOLDER_FALLBACK,
  endpointPlaceholderFor,
  resolveSparseCapability,
  shouldProbeSparseService,
  sparseProbeKey,
  sparseServiceProbeKey,
  sparseServiceVerdictFor,
  visionReferenceOptions,
} from "@/core/rag/config-form";
import type {
  RagConfigSource,
  RagConfigValues,
  RagConfigView,
} from "@/core/rag/types";

/**
 * A view where the file owns nothing: every field is either the operator's (`config_file`),
 * backed by an environment variable, or unset. Each test opts fields into file ownership.
 */
function view(
  over: Partial<RagConfigView["config"]> = {},
  sources: Record<string, RagConfigSource> = {},
): RagConfigView {
  return {
    // The form helpers read nothing but `config` / `sources`; the save-time verdict rides along.
    warning: null,
    config: {
      qdrant_url: "http://qdrant:6333",
      embedding_model: "qwen3.7-text-embedding",
      embedding_api_key: "",
      rerank_model: "qwen3-rerank",
      rerank_api_key: "",
      vlm_model: "Qwen/Qwen3-VL-30B-A3B-Instruct",
      extract_model: "deepseek-chat",
      judge_model: "deepseek-chat",
      mineru_api_token: "",
      embedding_provider: "dashscope",
      embedding_base_url: "",
      embedding_sparse_source: "provider",
      sparse_provider: null,
      sparse_base_url: "",
      sparse_model: "",
      sparse_api_key: "",
      rerank_provider: "dashscope",
      rerank_base_url: "",
      parse_provider: "mineru-cloud",
      parse_base_url: "",
      parse_tier: null,
      video: { asr_provider: "funasr", asr_model: "paraformer-zh" },
      ...over,
    },
    sources: {
      qdrant_url: "config_file",
      embedding_model: "config_file",
      embedding_api_key: "unset",
      rerank_model: "config_file",
      rerank_api_key: "env",
      vlm_model: "config_file",
      extract_model: "config_file",
      judge_model: "config_file",
      mineru_api_token: "unset",
      embedding_provider: "config_file",
      embedding_base_url: "config_file",
      embedding_sparse_source: "config_file",
      sparse_provider: "config_file",
      sparse_base_url: "config_file",
      sparse_model: "config_file",
      sparse_api_key: "unset",
      rerank_provider: "config_file",
      rerank_base_url: "config_file",
      parse_provider: "config_file",
      parse_base_url: "config_file",
      parse_tier: "config_file",
      "video.asr_provider": "config_file",
      "video.asr_model": "config_file",
      ...sources,
    },
  };
}

/** A view whose file owns one stored key. */
function viewWithStoredKey(): RagConfigView {
  return view(
    { embedding_api_key: MASKED_RAG_SECRET },
    { embedding_api_key: "ui" },
  );
}

afterEach(() => {
  fetchMock.fetch.mockReset();
});

describe("formValuesFromConfig", () => {
  it("maps the effective values and keeps a masked secret as-is", () => {
    const values = formValuesFromConfig(viewWithStoredKey());

    expect(values.embedding_model).toBe("qwen3.7-text-embedding");
    expect(values.embedding_api_key).toBe(MASKED_RAG_SECRET);
    expect(values.rerank_api_key).toBe("");
    expect(values.video).toEqual({
      asr_provider: "funasr",
      asr_model: "paraformer-zh",
    });
  });

  it("falls back to empty strings for an unset view", () => {
    const values = formValuesFromConfig({
      config: {},
      sources: {},
      warning: null,
    });

    expect(values.qdrant_url).toBe("");
    expect(values.embedding_api_key).toBe("");
    expect(values.video.asr_provider).toBe("funasr");
  });
});

describe("buildRagConfigInput", () => {
  it("submits nothing when nothing changed and the file owns nothing", () => {
    const current = view();

    expect(buildRagConfigInput(formValuesFromConfig(current), current)).toEqual({});
  });

  it("carries the file's own override forward so a partial edit cannot drop it", () => {
    const current = view({}, { rerank_model: "ui" });
    const values = formValuesFromConfig(current);
    values.extract_model = ""; // operator-owned: clearing it changes nothing

    expect(buildRagConfigInput(values, current)).toEqual({ rerank_model: "qwen3-rerank" });
  });

  it("clears a file-owned field explicitly", () => {
    const current = view({}, { rerank_model: "ui" });
    const values = formValuesFromConfig(current);
    values.rerank_model = "";

    expect(buildRagConfigInput(values, current)).toEqual({ rerank_model: "" });
  });

  it("submits a newly typed value for an operator-owned field", () => {
    const current = view();
    const values = formValuesFromConfig(current);
    values.embedding_model = "qwen3.7-text-embedding-v2";

    expect(buildRagConfigInput(values, current)).toEqual({
      embedding_model: "qwen3.7-text-embedding-v2",
    });
  });

  it("preserves an untouched stored secret with the sentinel", () => {
    const current = viewWithStoredKey();
    const values = formValuesFromConfig(current);
    values.embedding_model = "qwen3.7-text-embedding-v2";

    expect(buildRagConfigInput(values, current)).toEqual({
      embedding_model: "qwen3.7-text-embedding-v2",
      embedding_api_key: MASKED_RAG_SECRET,
    });
  });

  it("clears a stored secret when the input is emptied", () => {
    const current = viewWithStoredKey();
    const values = formValuesFromConfig(current);
    values.embedding_api_key = "";

    expect(buildRagConfigInput(values, current)).toEqual({ embedding_api_key: "" });
  });

  it("submits a rotated secret value", () => {
    const current = viewWithStoredKey();
    const values = formValuesFromConfig(current);
    values.embedding_api_key = "sk-rotated";

    expect(buildRagConfigInput(values, current)).toEqual({ embedding_api_key: "sk-rotated" });
  });

  it("leaves env-backed and unset secrets alone until they are typed into", () => {
    const current = view();
    const values = formValuesFromConfig(current);
    expect(buildRagConfigInput(values, current)).toEqual({});

    values.rerank_api_key = "sk-env-override";
    expect(buildRagConfigInput(values, current)).toEqual({ rerank_api_key: "sk-env-override" });
  });

  it("carries and updates the nested video block", () => {
    const current = view({}, { "video.asr_model": "ui" });
    const values = formValuesFromConfig(current);
    values.video.asr_provider = "whisper";

    expect(buildRagConfigInput(values, current)).toEqual({
      video: { asr_model: "paraformer-zh", asr_provider: "whisper" },
    });
  });

  it("keeps a service-tier ASR provider instead of normalising it back to a local engine", () => {
    // The provider select is an enum, not a two-value switch (spec 2026-09-28 D2): a value
    // outside the old pair used to be silently rewritten to `funasr` on load *and* on submit,
    // so the new tier could never be saved.
    const current = view({ video: { asr_provider: "dashscope", asr_model: "qwen-audio-3.1-asr-flash" } });
    const values = formValuesFromConfig(current);

    expect(values.video.asr_provider).toBe("dashscope");
    expect(buildRagConfigInput(values, current)).toEqual({});
  });

  it("round-trips the ASR address and key beside the other legs' fields", () => {
    // ① 乙 (2026-09-29): the leg's connection info lives at the top level, not inside `video`.
    const current = view(
      { asr_base_url: "https://dashscope.aliyuncs.com", asr_api_key: "" },
      { asr_base_url: "ui", asr_api_key: "unset" },
    );
    const values = formValuesFromConfig(current);

    expect(values.asr_base_url).toBe("https://dashscope.aliyuncs.com");
    expect(buildRagConfigInput(values, current)).toEqual({ asr_base_url: "https://dashscope.aliyuncs.com" });

    values.video.asr_provider = "openai-audio";
    values.asr_base_url = "http://127.0.0.1:8000/v1";
    values.asr_api_key = "sk-asr";
    expect(buildRagConfigInput(values, current)).toEqual({
      // The model is operator-owned here, so only the rows that actually changed are submitted.
      video: { asr_provider: "openai-audio" },
      asr_base_url: "http://127.0.0.1:8000/v1",
      asr_api_key: "sk-asr",
    });
  });

  it("trims what it submits", () => {
    const current = view();
    const values = formValuesFromConfig(current);
    values.vlm_model = "  Qwen/Qwen3-VL-8B  ";

    expect(buildRagConfigInput(values, current).vlm_model).toBe("Qwen/Qwen3-VL-8B");
  });
});

describe("isEmbeddingChange", () => {
  it("reports a changed embedding model, ignoring surrounding whitespace", () => {
    const current = view();
    const values = formValuesFromConfig(current);
    expect(isEmbeddingChange(values, current)).toBe(false);

    values.embedding_model = " qwen3.7-text-embedding ";
    expect(isEmbeddingChange(values, current)).toBe(false);

    values.embedding_model = "text-embedding-v4";
    expect(isEmbeddingChange(values, current)).toBe(true);
  });
});

describe("rag config client", () => {
  it("loads through the admin endpoint", async () => {
    fetchMock.fetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => view(),
    } as unknown as Response);

    const loaded = await loadRagConfig();

    expect(loaded.config.embedding_model).toBe("qwen3.7-text-embedding");
    const [url] = fetchMock.fetch.mock.calls[0]!;
    expect(String(url)).toContain("/api/rag/config");
  });

  it("PUTs the whole object and maps a 403 to isAdminRequired", async () => {
    fetchMock.fetch.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => view(),
    } as unknown as Response);

    await saveRagConfig({ embedding_model: "x" });

    const [url, init] = fetchMock.fetch.mock.calls[0]!;
    expect(String(url)).toContain("/api/rag/config");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body as string)).toEqual({ embedding_model: "x" });

    fetchMock.fetch.mockReset();
    fetchMock.fetch.mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ detail: "Admin privileges required" }),
    } as unknown as Response);

    await expect(saveRagConfig({})).rejects.toBeInstanceOf(RagConfigRequestError);
    await expect(saveRagConfig({})).rejects.toMatchObject({ isAdminRequired: true });
  });
});

describe("modelReferenceOptions", () => {
  const MODELS = [
    { name: "deepseek-chat", display_name: "DeepSeek Chat" },
    { name: "qwen-max", display_name: null },
  ];

  it("lists configured models after an explicit 'not configured' entry", () => {
    expect(modelReferenceOptions(MODELS, "qwen-max", "(未配置)")).toEqual([
      { value: MODEL_REFERENCE_NONE, label: "(未配置)" },
      { value: "deepseek-chat", label: "DeepSeek Chat" },
      { value: "qwen-max", label: "qwen-max" },
    ]);
  });

  it("keeps a stored value whose model was deleted", () => {
    const options = modelReferenceOptions(MODELS, "gone-model", "(未配置)");

    expect(options.at(-1)).toEqual({ value: "gone-model", label: "gone-model" });
  });

  it("does not duplicate a configured current value", () => {
    expect(
      modelReferenceOptions(MODELS, "deepseek-chat", "(未配置)").map((option) => option.value),
    ).toEqual([MODEL_REFERENCE_NONE, "deepseek-chat", "qwen-max"]);
  });
});

describe("judge model", () => {
  it("seeds the effective value and reports no change for it", () => {
    const current = view();

    expect(formValuesFromConfig(current).judge_model).toBe("deepseek-chat");
    expect(buildRagConfigInput(formValuesFromConfig(current), current)).toEqual({});
  });

  it("submits an override picked for an operator-owned judge", () => {
    const current = view();
    const values = formValuesFromConfig(current);
    values.judge_model = "qwen-max";

    expect(buildRagConfigInput(values, current)).toEqual({ judge_model: "qwen-max" });
  });

  it("carries a file-owned judge forward and clears it when emptied", () => {
    const current = view({}, { judge_model: "ui" });
    const values = formValuesFromConfig(current);

    expect(buildRagConfigInput(values, current)).toEqual({ judge_model: "deepseek-chat" });

    values.judge_model = "";
    expect(buildRagConfigInput(values, current)).toEqual({ judge_model: "" });
  });

  it("reports an edit as a change", () => {
    const current = view();
    const values = formValuesFromConfig(current);
    values.judge_model = "qwen-max";

    expect(hasFormChanges(values, current)).toBe(true);
  });
});

describe("RAG default model", () => {
  it("seeds the effective value and reports no change for it", () => {
    const current = view({ default_model: "yaml-default" });

    const values = formValuesFromConfig(current);

    expect(values.default_model).toBe("yaml-default");
    expect(hasFormChanges(values, current)).toBe(false);
    expect(buildRagConfigInput(values, current)).toEqual({});
  });

  it("seeds an empty string when nothing declares a default", () => {
    expect(formValuesFromConfig(view()).default_model).toBe("");
  });

  it("submits a newly picked value for an operator-owned default", () => {
    const current = view();
    const values = {
      ...formValuesFromConfig(current),
      default_model: "qwen3.7-max",
    };

    expect(buildRagConfigInput(values, current)).toEqual({
      default_model: "qwen3.7-max",
    });
  });

  it("withdraws the last file-owned override with an explicit empty string", () => {
    // The whole object is replaced, so "clear it" has to be *said*: an omitted key would be
    // read as a carry-forward. Cleared ⇒ `""`, which the server prunes into an absent key.
    const current = view(
      { default_model: "file-default" },
      { default_model: "ui" },
    );
    const values = {
      ...formValuesFromConfig(current),
      default_model: "",
    };

    expect(buildRagConfigInput(values, current)).toEqual({ default_model: "" });
  });

  it("withdraws one override while carrying the others", () => {
    const current = view(
      { default_model: "file-default", judge_model: "file-judge" },
      { default_model: "ui", judge_model: "ui" },
    );
    const values = {
      ...formValuesFromConfig(current),
      default_model: "",
    };

    expect(buildRagConfigInput(values, current)).toEqual({
      judge_model: "file-judge",
      default_model: "",
    });
  });

  it("carries a file-owned default forward while another setting is edited", () => {
    const current = view(
      { default_model: "file-default" },
      { default_model: "ui" },
    );
    const values = {
      ...formValuesFromConfig(current),
      embedding_model: "ui-embedding",
    };

    expect(buildRagConfigInput(values, current)).toEqual({
      default_model: "file-default",
      embedding_model: "ui-embedding",
    });
  });

  it("does not freeze an operator-owned default while another setting is edited", () => {
    // Editing a *different* row must not turn config.yaml's value into a UI override.
    const current = view({ default_model: "yaml-default" });
    const values = {
      ...formValuesFromConfig(current),
      embedding_model: "ui-embedding",
    };

    expect(buildRagConfigInput(values, current)).toEqual({
      embedding_model: "ui-embedding",
    });
  });

  it("counts picking a default as a change, and reverting it as none", () => {
    const current = view({ default_model: "yaml-default" });
    const seeded = formValuesFromConfig(current);

    expect(hasFormChanges({ ...seeded, default_model: "other" }, current)).toBe(
      true,
    );
    expect(
      hasFormChanges({ ...seeded, default_model: "  yaml-default  " }, current),
    ).toBe(false);
  });
});

describe("wiki and synthesis roles", () => {
  // The two roles that had no field at all before spec 2026-09-26. Same contract as every
  // other model-reference row — including the B-1-shaped guard: a file-owned override has to
  // survive an unrelated edit, or the whole-object PUT would silently drop it.
  const ROLES = ["wiki_model", "synthesis_model"] as const;
  const over = (field: (typeof ROLES)[number], value: string) =>
    ({ [field]: value }) as Partial<RagConfigValues>;
  const edited = (field: (typeof ROLES)[number], value: string) => ({
    ...formValuesFromConfig(view(over(field, "yaml-role"))),
    [field]: value,
  });

  it.each(ROLES)(
    "%s seeds the effective value and reports no change for it",
    (field) => {
      const current = view(over(field, "yaml-role"));
      const values = formValuesFromConfig(current);

      expect(values[field]).toBe("yaml-role");
      expect(hasFormChanges(values, current)).toBe(false);
      expect(buildRagConfigInput(values, current)).toEqual({});
    },
  );

  it.each(ROLES)(
    "%s seeds an empty string when nothing declares it",
    (field) => {
      expect(formValuesFromConfig(view())[field]).toBe("");
    },
  );

  it.each(ROLES)("%s is submitted when an operator picks one", (field) => {
    const current = view();
    const values = edited(field, "qwen3.7-max");

    expect(buildRagConfigInput(values, current)).toEqual({
      [field]: "qwen3.7-max",
    });
  });

  it.each(ROLES)(
    "%s survives an unrelated edit when the file owns it",
    (field) => {
      const current = view(
        { ...over(field, "file-role"), rerank_model: "qwen3-rerank" },
        { [field]: "ui" },
      );
      const values = {
        ...formValuesFromConfig(current),
        rerank_model: "qwen3-rerank-v2",
      };

      expect(buildRagConfigInput(values, current)).toEqual({
        [field]: "file-role",
        rerank_model: "qwen3-rerank-v2",
      });
    },
  );

  it.each(ROLES)("%s is withdrawn with an explicit empty string", (field) => {
    // `""` rather than an omitted key: the server reads an omission as carry-forward.
    const current = view(over(field, "file-role"), { [field]: "ui" });
    const values = {
      ...formValuesFromConfig(current),
      [field]: "",
    };

    expect(buildRagConfigInput(values, current)).toEqual({ [field]: "" });
  });

  it.each(ROLES)(
    "%s counts as a change when picked, and not once reverted",
    (field) => {
      const current = view(over(field, "yaml-role"));
      const seeded = formValuesFromConfig(current);

      expect(hasFormChanges({ ...seeded, [field]: "other" }, current)).toBe(
        true,
      );
      expect(
        hasFormChanges({ ...seeded, [field]: "  yaml-role  " }, current),
      ).toBe(false);
    },
  );
});

describe("thinking follow-chat toggles (spec 2026-10-03 D1=甲)", () => {
  // Five role slots, one boolean each: checked = this leg follows chat's thinking default.
  // A checkbox is two-state, so `false` is how the form *says* "not this leg" — an omitted
  // key would be read as a carry-forward by the whole-object PUT, just like the text rows.
  const FIELDS = [
    "extract_thinking",
    "wiki_thinking",
    "judge_thinking",
    "synthesis_thinking",
    "vlm_thinking",
  ] as const;
  const over = (field: (typeof FIELDS)[number], value: boolean | null) =>
    ({ [field]: value }) as Partial<RagConfigValues>;

  it.each(FIELDS)(
    "%s seeds false when nothing declares it, and that is no change",
    (field) => {
      const current = view();
      const values = formValuesFromConfig(current);

      expect(values[field]).toBe(false);
      expect(hasFormChanges(values, current)).toBe(false);
      expect(buildRagConfigInput(values, current)).toEqual({});
    },
  );

  it.each(FIELDS)(
    "%s seeds the stored boolean without marking a change",
    (field) => {
      const current = view(over(field, true));
      const values = formValuesFromConfig(current);

      expect(values[field]).toBe(true);
      expect(hasFormChanges(values, current)).toBe(false);
      expect(buildRagConfigInput(values, current)).toEqual({});
    },
  );

  it.each(FIELDS)("%s is submitted as true when it is switched on", (field) => {
    const current = view();
    const values = {
      ...formValuesFromConfig(current),
      [field]: true,
    };

    expect(hasFormChanges(values, current)).toBe(true);
    expect(buildRagConfigInput(values, current)).toEqual({ [field]: true });
  });

  it.each(FIELDS)("%s is submitted as false when it is switched off", (field) => {
    const current = view(over(field, true));
    const values = {
      ...formValuesFromConfig(current),
      [field]: false,
    };

    expect(hasFormChanges(values, current)).toBe(true);
    expect(buildRagConfigInput(values, current)).toEqual({ [field]: false });
  });

  it.each(FIELDS)(
    "%s counts as a change when toggled, and not once reverted",
    (field) => {
      const current = view();
      const seeded = formValuesFromConfig(current);
      const on = { ...seeded, [field]: true };

      expect(hasFormChanges(on, current)).toBe(true);
      expect(hasFormChanges({ ...on, [field]: false }, current)).toBe(false);
    },
  );

  it.each(FIELDS)(
    "%s survives an unrelated edit when the file owns it",
    (field) => {
      const current = view(
        { ...over(field, true), rerank_model: "qwen3-rerank" },
        { [field]: "ui" },
      );
      const values = {
        ...formValuesFromConfig(current),
        rerank_model: "qwen3-rerank-v2",
      };

      expect(buildRagConfigInput(values, current)).toEqual({
        [field]: true,
        rerank_model: "qwen3-rerank-v2",
      });
    },
  );

  it("carries a stored false forward too — false is a value, not an absence", () => {
    const current = view(
      { extract_thinking: false, rerank_model: "qwen3-rerank" },
      { extract_thinking: "ui" },
    );
    const values = {
      ...formValuesFromConfig(current),
      rerank_model: "qwen3-rerank-v2",
    };

    expect(buildRagConfigInput(values, current)).toEqual({
      extract_thinking: false,
      rerank_model: "qwen3-rerank-v2",
    });
  });
});

describe("hasFormChanges", () => {
  it("is false right after seeding, even when the file owns fields", () => {
    const current = viewWithStoredKey();

    expect(hasFormChanges(formValuesFromConfig(current), current)).toBe(false);
  });

  it("is true once a field is edited and false again when it is reverted", () => {
    const current = view();
    const values = formValuesFromConfig(current);

    values.rerank_model = "qwen3-rerank-v2";
    expect(hasFormChanges(values, current)).toBe(true);

    values.rerank_model = current.config.rerank_model!;
    expect(hasFormChanges(values, current)).toBe(false);
  });

  it("is true when a file-owned field is cleared", () => {
    const current = viewWithStoredKey();
    const values = formValuesFromConfig(current);

    values.embedding_api_key = "";

    expect(hasFormChanges(values, current)).toBe(true);
  });

  it("ignores whitespace-only edits", () => {
    const current = view();
    const values = formValuesFromConfig(current);

    values.vlm_model = ` ${current.config.vlm_model} `;

    expect(hasFormChanges(values, current)).toBe(false);
  });
});


describe("caption model picker", () => {
  const MODELS = [
    { name: "gpt-5", model: "gpt-5", display_name: "GPT-5", supports_vision: true, provider: "openai-compatible" },
    { name: "vl", model: "Qwen/Qwen3-VL-30B", display_name: "", supports_vision: true, provider: "openai-compatible" },
    { name: "claude", model: "claude-x", display_name: "Claude X", supports_vision: true, provider: "anthropic" },
    { name: "text-only", model: "deepseek-chat", display_name: "DeepSeek", supports_vision: false, provider: "openai-compatible" },
    { name: "legacy", model: "m", display_name: "Legacy", supports_vision: true },
  ];

  it("lists every vision-capable entry after the default entry", () => {
    expect(visionReferenceOptions(MODELS, "gpt-5", "(默认)")).toEqual([
      { value: MODEL_REFERENCE_NONE, label: "(默认)" },
      { value: "gpt-5", label: "GPT-5" },
      // A blank display name falls back to the registry name.
      { value: "vl", label: "vl" },
      { value: "claude", label: "Claude X" },
      { value: "legacy", label: "Legacy" },
    ]);
  });

  it("keeps an Anthropic entry — the caption client speaks its protocol too — and drops non-vision entries", () => {
    const values = visionReferenceOptions(MODELS, "", "(默认)").map((option) => option.value);

    expect(values).toContain("claude");
    expect(values).not.toContain("text-only");
  });

  it("keeps a stored value that names no entry, so a save cannot silently drop it", () => {
    expect(visionReferenceOptions(MODELS, "qwen3.7-flash", "(默认)").at(-1)).toEqual({
      value: "qwen3.7-flash",
      label: "qwen3.7-flash",
    });
  });

  it("requires vision support, whichever provider serves the entry", () => {
    const anthropic = { name: "a", model: "a", supports_vision: true };
    const textOnly = { ...anthropic, supports_vision: false };
    const openaiVision = { ...anthropic, provider: "openai-compatible" };

    expect(isCaptionCapable({ ...anthropic, provider: "anthropic" })).toBe(true);
    // Dropping the provider test turns nothing loose: no vision still means no candidacy.
    expect(isCaptionCapable(textOnly)).toBe(false);
    expect(isCaptionCapable({ name: "b", model: "b" })).toBe(false);
    expect(isCaptionCapable(openaiVision)).toBe(true);
  });
});

describe("provider dimension (spec 2026-09-14 §4.1)", () => {
  it("seeds the fields and keeps the effective defaults when the file declares none", () => {
    const values = formValuesFromConfig(view());

    expect(values.embedding_provider).toBe("dashscope");
    expect(values.embedding_sparse_source).toBe("provider");
    expect(values.rerank_provider).toBe("dashscope");
    expect(values.parse_provider).toBe("mineru-cloud");
    expect(values.parse_tier).toBe("");
    expect(values.embedding_base_url).toBe("");
  });

  it("offers the four service tiers plus the empty option, in order", () => {
    // Mirrors the backend's `parse_tier` Literal (spec 2026-09-24 §4.6); the empty option means
    // "let the service decide", and the retired `vlm` / `hybrid` pair must not come back.
    expect(PARSE_TIER_OPTIONS).toEqual([
      "",
      "flash",
      "basic",
      "standard",
      "advanced",
    ]);
  });

  it("submits the parse tier the admin picked", () => {
    const base = formValuesFromConfig(view());
    const input = buildRagConfigInput({ ...base, parse_tier: "flash" }, view());

    expect(input.parse_tier).toBe("flash");
  });

  it("submits the provider and endpoint the admin picked, and nothing else", () => {
    const base = formValuesFromConfig(view());
    const input = buildRagConfigInput(
      {
        ...base,
        rerank_provider: "generic-rerank",
        rerank_base_url: "http://localhost:8000",
        parse_provider: "mineru-local",
        parse_base_url: "http://localhost:30000",
      },
      view(),
    );

    expect(input.rerank_provider).toBe("generic-rerank");
    expect(input.rerank_base_url).toBe("http://localhost:8000");
    expect(input.parse_provider).toBe("mineru-local");
    expect(input.parse_base_url).toBe("http://localhost:30000");
    // An operator-owned field this edit never touched stays out of the payload.
    expect(input.embedding_provider).toBeUndefined();
  });

  it("carries the file's own provider override forward", () => {
    const owned = view({ embedding_provider: "openai-compatible" }, { embedding_provider: "ui" });

    expect(buildRagConfigInput(formValuesFromConfig(owned), owned).embedding_provider).toBe("openai-compatible");
  });

  it("treats sparse_api_key as a secret", () => {
    const owned = view({ sparse_api_key: MASKED_RAG_SECRET }, { sparse_api_key: "ui" });

    expect(buildRagConfigInput(formValuesFromConfig(owned), owned).sparse_api_key).toBe(MASKED_RAG_SECRET);
    expect(buildRagConfigInput({ ...formValuesFromConfig(owned), sparse_api_key: "" }, owned).sparse_api_key).toBe("");
    expect(buildRagConfigInput({ ...formValuesFromConfig(owned), sparse_api_key: "sk-new" }, owned).sparse_api_key).toBe(
      "sk-new",
    );
  });
});

describe("解析语种与模型版本 (spec 2026-09-29 D1)", () => {
  it("maps the stored parse language and version back into the form", () => {
    const values = formValuesFromConfig(
      view({ parse_language: "japan", parse_model_version: "pipeline" }),
    );

    expect(values.parse_language).toBe("japan");
    expect(values.parse_model_version).toBe("pipeline");
  });

  it("falls back to the empty option when the file declares neither", () => {
    const values = formValuesFromConfig(view());

    expect(values.parse_language).toBe("");
    expect(values.parse_model_version).toBe("");
  });

  it("carries a file-owned parse language and version forward", () => {
    const owned = view(
      { parse_language: "korean", parse_model_version: "pipeline" },
      { parse_language: "ui", parse_model_version: "ui" },
    );

    const input = buildRagConfigInput(formValuesFromConfig(owned), owned);

    expect(input.parse_language).toBe("korean");
    expect(input.parse_model_version).toBe("pipeline");
  });

  it("withdraws a file-owned enum with null, never an empty string", () => {
    // `""` fails the Literal on the PUT body (422), so a cleared override has to be said
    // as `null` — true for the six pre-existing selects too, same loop (spec §6.2 末条).
    const owned = view(
      { parse_language: "korean", parse_tier: "flash" },
      { parse_language: "ui", parse_tier: "ui" },
    );

    const input = buildRagConfigInput(
      { ...formValuesFromConfig(owned), parse_language: "", parse_tier: "" },
      owned,
    );

    expect(input.parse_language).toBeNull();
    expect(input.parse_tier).toBeNull();
  });
});

describe("isEmbeddingChange covers the whole provider dimension", () => {
  it("reports a changed provider, endpoint or sparse source, not only the model", () => {
    const base = formValuesFromConfig(view());

    expect(isEmbeddingChange(base, view())).toBe(false);
    expect(isEmbeddingChange({ ...base, embedding_provider: "openai-compatible" }, view())).toBe(true);
    expect(isEmbeddingChange({ ...base, embedding_base_url: "http://localhost:8080/v1" }, view())).toBe(true);
    expect(isEmbeddingChange({ ...base, embedding_sparse_source: "bm25" }, view())).toBe(true);
  });
});

describe("hasFormChanges covers the provider fields", () => {
  it("reports a provider edit as a change", () => {
    const base = formValuesFromConfig(view());

    expect(hasFormChanges(base, view())).toBe(false);
    expect(hasFormChanges({ ...base, parse_provider: "mineru-local" }, view())).toBe(true);
    expect(hasFormChanges({ ...base, embedding_base_url: "http://x" }, view())).toBe(true);
  });
});

/**
 * 稀疏来源与嵌入提供商能力的交叉判定（spec 2026-09-16 §3 D2）。
 *
 * 这一层是纯逻辑，所以「拿表单当前值判定」这条由它来钉：DOM 里驱动 Radix Select 不可靠
 * （见 functional-models.dom.test.tsx 的注释），而这里可以直接把「表单里的 provider」与
 * 「已保存的 provider」构造成不同的两个值。
 */
describe("isSparseSourceUnsupported", () => {
  const PROVIDERS = [
    {
      provider_id: "dashscope",
      emits_sparse: true,
      has_fixed_endpoint: true,
      default_endpoint: "https://dashscope.aliyuncs.com",
    },
    {
      provider_id: "openai-compatible",
      emits_sparse: false,
      has_fixed_endpoint: false,
      default_endpoint: null,
    },
  ];
  const form = (over: Record<string, unknown> = {}) => ({
    ...formValuesFromConfig(
      view({
        embedding_provider: "dashscope",
        embedding_sparse_source: "provider",
      }),
    ),
    ...over,
  });

  it("only objects to a dense-only provider that is asked for the sparse half", () => {
    expect(
      isSparseSourceUnsupported(
        form({ embedding_provider: "openai-compatible" }),
        PROVIDERS,
      ),
    ).toBe(true);
    // Same provider, sparse half sourced elsewhere.
    expect(
      isSparseSourceUnsupported(
        form({
          embedding_provider: "openai-compatible",
          embedding_sparse_source: "bm25",
        }),
        PROVIDERS,
      ),
    ).toBe(false);
    // Provider that can do it.
    expect(isSparseSourceUnsupported(form(), PROVIDERS)).toBe(false);
    expect(
      isSparseSourceUnsupported(
        form({ embedding_sparse_source: "external" }),
        PROVIDERS,
      ),
    ).toBe(false);
  });

  it("judges the form's own provider, not the one the response was seeded with", () => {
    const seeded = formValuesFromConfig(
      view({
        embedding_provider: "dashscope",
        embedding_sparse_source: "provider",
      }),
    );
    expect(seeded.embedding_provider).toBe("dashscope");
    expect(isSparseSourceUnsupported(seeded, PROVIDERS)).toBe(false);

    // …and the moment the admin switches the picker, the pair is judged as it now stands.
    expect(
      isSparseSourceUnsupported(
        { ...seeded, embedding_provider: "openai-compatible" },
        PROVIDERS,
      ),
    ).toBe(true);
  });

  it("stays quiet when the capabilities are unknown", () => {
    const editing = form({ embedding_provider: "openai-compatible" });
    expect(isSparseSourceUnsupported(editing, undefined)).toBe(false);
    expect(isSparseSourceUnsupported(editing, [])).toBe(false);
    // A provider the server did not list is unknown too, not "unsupported".
    expect(
      isSparseSourceUnsupported(
        form({
          embedding_provider: "dashscope",
          embedding_sparse_source: "provider",
        }),
        [
          {
            provider_id: "openai-compatible",
            emits_sparse: false,
            has_fixed_endpoint: false,
            default_endpoint: null,
          },
        ],
      ),
    ).toBe(false);
  });
});

/**
 * 稀疏能力是三态（spec 2026-09-16 §3 D2）：名单答得了「provider 这个方言支不支持」，
 * 答不了「这个具体模型支不支持」——后者只有一次真实探测能答。合成规则把两个来源并成一个
 * 结论，且**探测结论只对它被测的那组值有效**（换了 model / provider / 地址就当没测过）：
 * 沿用旧结论会把一个刚被否掉的值放过去。
 */
describe("resolveSparseCapability", () => {
  const PROVIDERS = [
    {
      provider_id: "dashscope",
      emits_sparse: true,
      has_fixed_endpoint: true,
      default_endpoint: "https://dashscope.aliyuncs.com",
    },
    {
      provider_id: "openai-compatible",
      emits_sparse: false,
      has_fixed_endpoint: false,
      default_endpoint: null,
    },
  ];
  const form = (over: Record<string, unknown> = {}) => ({
    ...formValuesFromConfig(
      view({
        embedding_provider: "dashscope",
        embedding_sparse_source: "provider",
        embedding_model: "qwen3.7-text-embedding",
      }),
    ),
    ...over,
  });
  const probed = (
    values: ReturnType<typeof form>,
    status: "supported" | "unsupported" | "unverifiable",
  ) => ({ key: sparseProbeKey(values), status });

  it("answers from the allowlist when that is already the whole answer", () => {
    // A dialect that cannot carry a sparse half needs no call at all.
    expect(
      resolveSparseCapability(
        form({ embedding_provider: "openai-compatible" }),
        PROVIDERS,
        null,
      ),
    ).toBe("unsupported");
  });

  it("answers from the probe when the question is model-level", () => {
    const values = form();
    expect(
      resolveSparseCapability(values, PROVIDERS, probed(values, "supported")),
    ).toBe("supported");
    expect(
      resolveSparseCapability(values, PROVIDERS, probed(values, "unsupported")),
    ).toBe("unsupported");
    // "Could not check" is not "cannot do it": refusing here would reject working setups.
    expect(
      resolveSparseCapability(
        values,
        PROVIDERS,
        probed(values, "unverifiable"),
      ),
    ).toBe("unknown");
  });

  it("does not reuse a verdict taken for other values", () => {
    const values = form();
    const stale = probed(values, "supported");
    expect(
      resolveSparseCapability(
        form({ embedding_model: "bge-m3" }),
        PROVIDERS,
        stale,
      ),
    ).toBe("unknown");
    expect(
      resolveSparseCapability(
        form({ embedding_base_url: "https://elsewhere.example.com" }),
        PROVIDERS,
        stale,
      ),
    ).toBe("unknown");
    expect(
      resolveSparseCapability(
        form({ embedding_provider: "openai-compatible" }),
        PROVIDERS,
        stale,
      ),
    ).toBe("unsupported"); // the allowlist still knows; only the probe's half is void
  });

  it("stays unknown until something has actually been probed", () => {
    expect(resolveSparseCapability(form(), PROVIDERS, null)).toBe("unknown");
    // A server that predates the capability block cannot be answered for — and must not be
    // answered with a guess either.
    expect(resolveSparseCapability(form(), undefined, null)).toBe("unknown");
    expect(resolveSparseCapability(form(), [], null)).toBe("unknown");
  });
});

describe("sparseProbeKey", () => {
  const form = (over: Record<string, unknown> = {}) => ({
    ...formValuesFromConfig(view({ embedding_sparse_source: "provider" })),
    ...over,
  });

  it("binds a verdict to the provider, the model and the endpoint", () => {
    expect(sparseProbeKey(form())).toBe("dashscope|qwen3.7-text-embedding|");
    expect(
      sparseProbeKey(
        form({
          embedding_provider: "openai-compatible",
          embedding_model: "bge-m3",
          embedding_base_url: "https://api.example.com",
        }),
      ),
    ).toBe("openai-compatible|bge-m3|https://api.example.com");
  });

  it("ignores the fields a probe does not depend on", () => {
    // The verdict is about (provider, model, endpoint) — the sparse source is the question
    // being asked, and rerank/judge/… are other legs entirely.
    const base = form();
    expect(sparseProbeKey({ ...base, embedding_sparse_source: "bm25" })).toBe(
      sparseProbeKey(base),
    );
    expect(sparseProbeKey({ ...base, rerank_model: "other" })).toBe(
      sparseProbeKey(base),
    );
  });
});

describe("isSparseProviderOptionDisabled", () => {
  it("disables the follow-the-model option only on a known refusal", () => {
    expect(isSparseProviderOptionDisabled("unsupported")).toBe(true);
    // Supported and "could not check" both stay selectable: the second one is the whole
    // point of the third state (a network failure must not lock a working configuration).
    expect(isSparseProviderOptionDisabled("supported")).toBe(false);
    expect(isSparseProviderOptionDisabled("unknown")).toBe(false);
  });
});

/**
 * 「独立稀疏服务」但没挑提供商 —— 这份配置后端**必定拒绝**（`external` 需要具体的
 * `sparse_provider`），而界面上原来既不提示、也能保存，直到那一次 400 才知道。
 * 这是同一条纪律的最后一个洞：能确定会被拒的组合，编辑期就要说。
 */
describe("isSparseServiceUnconfigured", () => {
  const form = (over: Record<string, unknown> = {}) => ({
    ...formValuesFromConfig(view({ embedding_sparse_source: "external" })),
    ...over,
  });

  it("objects to an external service with no provider chosen", () => {
    // The empty id is what a fresh external config seeds (Radix needs a non-empty value, so
    // "not chosen" travels as ""), and the runtime refuses exactly that pair.
    expect(isSparseServiceUnconfigured(form({ sparse_provider: "" }))).toBe(
      true,
    );
    expect(
      isSparseServiceUnconfigured(form({ sparse_provider: "tei-sparse" })),
    ).toBe(false);
  });

  it("leaves the other two sources alone", () => {
    expect(
      isSparseServiceUnconfigured(
        form({ embedding_sparse_source: "provider", sparse_provider: "" }),
      ),
    ).toBe(false);
    expect(
      isSparseServiceUnconfigured(
        form({ embedding_sparse_source: "bm25", sparse_provider: "" }),
      ),
    ).toBe(false);
  });
});

/**
 * 外部稀疏服务的连通性探针的前端纯逻辑（spec 2026-09-16 connectivity §3 D4）：**什么时候该探**、
 * **结论属于谁**。这两件事决定了「地址改一下」会不会带上旧结论、以及会不会对着空地址发请求。
 */
describe("sparse service probe", () => {
  const form = (over: Record<string, unknown> = {}) => ({
    ...formValuesFromConfig(
      view({
        embedding_sparse_source: "external",
        sparse_provider: "tei-sparse",
        sparse_base_url: "http://127.0.0.1:8081",
      }),
    ),
    ...over,
  });

  it("asks only when the form actually uses an external service with an address", () => {
    expect(shouldProbeSparseService(form())).toBe(true);
    // Nothing to reach yet.
    expect(shouldProbeSparseService(form({ sparse_base_url: "" }))).toBe(false);
    expect(shouldProbeSparseService(form({ sparse_base_url: "   " }))).toBe(
      false,
    );
    // No provider chosen: `external` requires one, so there is nothing to call.
    expect(shouldProbeSparseService(form({ sparse_provider: "" }))).toBe(false);
    // The other two sources never leave the machine.
    expect(
      shouldProbeSparseService(form({ embedding_sparse_source: "provider" })),
    ).toBe(false);
    expect(
      shouldProbeSparseService(form({ embedding_sparse_source: "bm25" })),
    ).toBe(false);
  });

  it("binds a verdict to the address it was taken for, and to whether a key exists", () => {
    const values = form();
    expect(sparseServiceProbeKey(values, false)).toBe(
      "tei-sparse|http://127.0.0.1:8081|nokey",
    );
    expect(sparseServiceProbeKey(values, true)).toBe(
      "tei-sparse|http://127.0.0.1:8081|key",
    );
    // A trim is not an edit.
    expect(
      sparseServiceProbeKey(
        form({ sparse_base_url: " http://127.0.0.1:8081 " }),
        false,
      ),
    ).toBe(sparseServiceProbeKey(values, false));
  });

  it("hands back a verdict only for the values it was taken for", () => {
    const values = form();
    const key = sparseServiceProbeKey(values, false);
    expect(
      sparseServiceVerdictFor(values, false, { key, status: "unreachable" }),
    ).toEqual({ key, status: "unreachable" });
    // Another address is another question — and so is "a key appeared".
    expect(
      sparseServiceVerdictFor(
        form({ sparse_base_url: "http://127.0.0.1:8082" }),
        false,
        { key, status: "ok" },
      ),
    ).toBeNull();
    expect(
      sparseServiceVerdictFor(values, true, { key, status: "ok" }),
    ).toBeNull();
    expect(sparseServiceVerdictFor(values, false, null)).toBeNull();
  });
});

/**
 * 嵌入侧的提供商选项与地址占位（spec 2026-09-25 rag-endpoint-unlock）：能力块的
 * `default_endpoint` 只作灰字占位（不落值、不回落），没有默认的 provider 退
 * `https://api.example.com/v1`。判据来自能力块，不写死 provider 名——加第二家之后就不会漏。
 */
describe("embedding provider options and the endpoint placeholder", () => {
  const PROVIDERS = [
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

  it("offers the Ark dialect alongside the other two", () => {
    expect(EMBEDDING_PROVIDER_OPTIONS).toContain("volcengine-ark");
    // The picker renders this order; the two dual-path dialects sit together.
    expect([...EMBEDDING_PROVIDER_OPTIONS]).toEqual([
      "dashscope",
      "volcengine-ark",
      "openai-compatible",
    ]);
  });

  it("offers the vendor default as the placeholder hint and falls back to example.com", () => {
    // Spec 2026-09-25 rag-endpoint-unlock: the default endpoint is only a grey hint —
    // never a value, never a runtime fallback.
    expect(endpointPlaceholderFor(PROVIDERS, "dashscope")).toBe(
      "https://dashscope.aliyuncs.com",
    );
    expect(endpointPlaceholderFor(PROVIDERS, "volcengine-ark")).toBe(
      "https://ark.cn-beijing.volces.com",
    );
    expect(endpointPlaceholderFor(PROVIDERS, "openai-compatible")).toBe(
      ENDPOINT_PLACEHOLDER_FALLBACK,
    );
    expect(endpointPlaceholderFor(undefined, "dashscope")).toBe(
      ENDPOINT_PLACEHOLDER_FALLBACK,
    );
  });
});

/**
 * The rerank leg answers the *same* question as the embedding one, from its own block
 * (spec 2026-09-25 rag-endpoint-unlock). Both legs read one shared helper
 * (`endpointPlaceholderFor`) so the judgement cannot drift into two copies — which is
 * exactly how the rerank row once ended up hardcoding a provider name.
 */
describe("rerank placeholder reads its own capability block", () => {
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
  ];

  it("hints the rerank block's own default and falls back to example.com", () => {
    // Spec 2026-09-25 rag-endpoint-unlock: the rerank leg mirrors the embedding one —
    // its own capability block supplies the hint, and there is no lock any more.
    expect(endpointPlaceholderFor(RERANK_PROVIDERS, "dashscope")).toBe(
      "https://dashscope.aliyuncs.com",
    );
    expect(endpointPlaceholderFor(RERANK_PROVIDERS, "generic-rerank")).toBe(
      ENDPOINT_PLACEHOLDER_FALLBACK,
    );
    expect(endpointPlaceholderFor(undefined, "dashscope")).toBe(
      ENDPOINT_PLACEHOLDER_FALLBACK,
    );
  });
});

describe("dimension field round-trip (spec 2026-09-26 §3 维度字段的往返)", () => {
  it("seeds the stored width as text and submits it as a number", () => {
    const current = view({ embedding_dimension: 1536 }, { embedding_dimension: "ui" });
    const values = formValuesFromConfig(current);
    expect(values.embedding_dimension).toBe("1536");

    // 未改动 ⇒ 原样携带（数字，不是字符串）——这是"任何一次保存都别把它抹掉"的那条。
    values.rerank_model = "qwen3-rerank-v2";
    expect(buildRagConfigInput(values, current)).toEqual({
      rerank_model: "qwen3-rerank-v2",
      embedding_dimension: 1536,
    });
  });

  it("clears a file-owned width with an empty input", () => {
    const current = view({ embedding_dimension: 1536 }, { embedding_dimension: "ui" });
    const values = formValuesFromConfig(current);

    values.embedding_dimension = "";
    expect(buildRagConfigInput(values, current)).toEqual({ embedding_dimension: null });
  });

  it("does not freeze an operator-owned width into the file", () => {
    const current = view({ embedding_dimension: 1024 });
    const values = formValuesFromConfig(current);

    values.rerank_model = "qwen3-rerank-v2";
    expect(buildRagConfigInput(values, current)).toEqual({
      rerank_model: "qwen3-rerank-v2",
    });
  });

  it("never submits a non-numeric width", () => {
    const current = view({}, { embedding_dimension: "ui" });
    const values = formValuesFromConfig(current);

    values.embedding_dimension = "12x";
    expect(buildRagConfigInput(values, current)).toEqual({});
  });

  it("counts the width as a change, and knows when it is back to the seeded value", () => {
    const current = view({ embedding_dimension: 1024 }, { embedding_dimension: "ui" });
    const values = formValuesFromConfig(current);
    expect(hasFormChanges(values, current)).toBe(false);
    expect(isEmbeddingChange(values, current)).toBe(false);

    values.embedding_dimension = "1536";
    expect(hasFormChanges(values, current)).toBe(true);
    expect(isEmbeddingChange(values, current)).toBe(true);

    values.embedding_dimension = "1024";
    expect(hasFormChanges(values, current)).toBe(false);
  });
});

describe("probe keys for the dimension row and the leg dots (spec 2026-09-26 §3 / D5-5)", () => {
  const values = formValuesFromConfig(view());

  it("binds the dimension answer to the provider / model / endpoint, not to the width", () => {
    const base = dimensionProbeKey(values);
    expect(base).not.toBe("");

    const other = { ...values, embedding_dimension: "1536" };
    expect(dimensionProbeKey(other)).toBe(base);
    expect(dimensionProbeKey({ ...values, embedding_model: "bge-m3" })).not.toBe(base);
  });

  it("binds a leg dot to its own leg's coordinates, the width in force, and key presence", () => {
    const withWidth = formValuesFromConfig(
      view({ embedding_dimension: 1024 }, { embedding_dimension: "ui" }),
    );
    const embedding = connectivityProbeKey("embedding", withWidth, true);
    expect(embedding).toContain("1024");
    expect(embedding).toContain("key");
    expect(connectivityProbeKey("embedding", withWidth, false)).not.toBe(embedding);
    expect(
      connectivityProbeKey("embedding", { ...withWidth, embedding_dimension: "1536" }, true),
    ).not.toBe(embedding);
    // 重排腿没有维度这一问（spec §3）。
    expect(connectivityProbeKey("rerank", withWidth, true)).not.toContain("embedding");
  });
});


describe("改宽度 = 迁移的那一次保存 (spec 2026-09-26 D5-7)", () => {
  it("compares the effective widths, so a blank declaration equals 1024", () => {
    const live = view({ embedding_dimension: null });
    const values = { ...formValuesFromConfig(live), embedding_dimension: "1024" };

    expect(changesEmbeddingDimension(values, live)).toBe(false);
  });

  it("sees a real move as a change, however it was typed", () => {
    const live = view({ embedding_dimension: null });

    expect(
      changesEmbeddingDimension(
        { ...formValuesFromConfig(live), embedding_dimension: "1536" },
        live,
      ),
    ).toBe(true);
  });

  it("treats clearing a declaration as a change back to the default", () => {
    const live = view({ embedding_dimension: 1536 });
    const values = { ...formValuesFromConfig(live), embedding_dimension: "" };

    expect(changesEmbeddingDimension(values, live)).toBe(true);
  });

  it("treats an untouched width as no change at all", () => {
    const live = view({ embedding_dimension: 1536 });

    expect(changesEmbeddingDimension(formValuesFromConfig(live), live)).toBe(false);
  });
});

describe("ASR model menu and the provider switch (spec 2026-09-27 §2 D2)", () => {
  it("rewrites a value the target engine cannot load to that engine's first menu row", () => {
    expect(asrModelForProviderSwitch("whisper", "paraformer-zh")).toBe("small");
  });

  it("rewrites a whisper name when switching to funasr", () => {
    expect(asrModelForProviderSwitch("funasr", "tiny")).toBe("paraformer-zh");
  });

  it("keeps everything that is not a whisper name when switching to funasr", () => {
    // funasr is an open set (any ModelScope id, or a local directory) — its menu is not a filter.
    for (const value of [
      "paraformer-en-spk",
      "iic/SenseVoiceSmall",
      "./models/paraformer",
    ]) {
      expect(asrModelForProviderSwitch("funasr", value)).toBe(value);
    }
  });

  it("takes each engine's default from its own menu's first row", () => {
    expect(ASR_MODEL_MENU.whisper[0]).toBe("small");
    expect(ASR_MODEL_MENU.funasr[0]).toBe("paraformer-zh");
    expect(asrModelForProviderSwitch("whisper", "")).toBe(
      ASR_MODEL_MENU.whisper[0],
    );
    expect(asrModelForProviderSwitch("funasr", "tiny")).toBe(
      ASR_MODEL_MENU.funasr[0],
    );
  });

  it("leaves a legal whisper name alone even when the menu does not offer it", () => {
    for (const value of ["turbo", "large"]) {
      expect(asrModelForProviderSwitch("whisper", value)).toBe(value);
    }
  });

  it("judges against every whisper name, not against the six menu rows", () => {
    // A menu-sized judgement would let these through to funasr, which fails only at ingest.
    for (const value of ["turbo", "large", "tiny.en"]) {
      expect(asrModelForProviderSwitch("funasr", value)).toBe("paraformer-zh");
    }
  });
});
