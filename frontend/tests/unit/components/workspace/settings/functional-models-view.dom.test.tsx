/**
 * The provider dimension's *display* rules in the RAG functional-model view
 * (spec 2026-09-14 rag model provider adaptation §4.5, revised 2026-09-15).
 *
 * Two rules are load-bearing and are what these tests pin:
 *
 * 1. Every provider-driven row is **present**; a row the current provider fixes is shown
 *    **locked** with its reason instead of disappearing. A control that vanishes on a
 *    provider switch reads as a missing feature, and the tall cells used to push the two
 *    retrieval columns out of alignment.
 * 2. The sparse settings live behind the advanced disclosure, and its four dependent rows
 *    follow rule 1: unlocked together when the source is `external`, locked together otherwise.
 *
 * The display is driven by the *seeded* config, so each case renders the view once with a
 * different stored provider instead of driving the Radix dropdown — that keeps the test
 * about the rule rather than about Radix's portal behavior.
 */

import { readFileSync } from "node:fs";
import path from "node:path";

import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { FunctionalModelsView } from "@/components/workspace/settings/functional-models-view";
import type { RagConfigValues, RagConfigView } from "@/core/rag/types";

const FRONTEND_ROOT = path.resolve(__dirname, "../../../../..");

const hooks = rs.hoisted(() => ({ view: null as RagConfigView | null }));
/** Per-test model catalogues: the two sources the view may pick candidates from differ. */
const catalogues = rs.hoisted(() => ({
  models: [] as Array<Record<string, unknown>>,
  managed: [] as Array<Record<string, unknown>>,
}));

/**
 * Every label resolves to its own key, so an assertion can name the i18n key directly. The
 * count-taking keys answer as functions (a plain string would throw when called).
 */
const KEYS = new Proxy({} as Record<string, unknown>, {
  get: (_target, key) =>
    key === "advancedSettings" ||
    key === "subsetSelected" ||
    key === "thinkingMenuState"
      ? (count: number) => `${String(key)}(${count})`
      : String(key),
});

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: { common: KEYS, settings: { models: KEYS, functionalModels: KEYS } },
  }),
}));

rs.mock("@/core/rag/hooks", () => ({
  useRagConfig: () => ({ view: hooks.view, isLoading: false, error: null }),
  useSaveRagConfig: () => ({ isPending: false, mutate: rs.fn() }),
  // 宽度迁移的状态面：这些用例不碰它，保持"从没跑过"（没有状态行、也不挡保存）。
  useRagMigrationStatus: () => ({ data: undefined }),
  // The capability probe only decorates the sparse-source row; these display-rule cases
  // never reach it, so it stays idle (no verdict, nothing in flight).
  useProbeSparseCapability: () => ({
    isPending: false,
    data: undefined,
    mutate: rs.fn(),
  }),
  // The sparse-service probe only decorates the address row; these display-rule cases never reach
  // it, so it stays idle too.
  useProbeSparseService: () => ({
    isPending: false,
    data: undefined,
    mutate: rs.fn(),
  }),
  // The dimension probe and the two title dots only decorate the retrieval group; idle here.
  useProbeDimensions: () => ({
    isPending: false,
    data: undefined,
    variables: undefined,
    mutate: rs.fn(),
  }),
  useProbeConnectivity: () => ({
    isPending: false,
    data: undefined,
    variables: undefined,
    mutate: rs.fn(),
  }),
  // The ASR row's own probe (spec 2026-09-28 D7) — same idle shape as the others.
  useProbeAsrService: () => ({
    isPending: false,
    data: undefined,
    variables: undefined,
    mutate: rs.fn(),
  }),
}));

rs.mock("@/core/models/hooks", () => ({
  useModels: () => ({ models: catalogues.models }),
  useModelsConfig: () => ({ config: { models: catalogues.managed } }),
}));

// The rebuild entry is library-scoped and its hooks poll; these display-rule cases only
// need the row to render, so the entry stays inert (no library, idle, nothing pending).
rs.mock("@/core/knowledge/hooks", () => ({
  useKnowledgeBases: () => ({ data: [], isLoading: false, error: null }),
  useReindexStatus: () => ({ data: undefined }),
  useReindexKnowledgeBase: () => ({ mutate: rs.fn(), isPending: false }),
}));

rs.mock("sonner", () => ({
  toast: { success: rs.fn(), info: rs.fn() },
}));

/**
 * What the embedding allowlist reports: which dialects ship a default endpoint (the grey
 * placeholder hint now, never a lock — spec 2026-09-25 rag-endpoint-unlock) and where they
 * point. Mirrors the real response — the view reads the hint from *this*, not from a
 * provider name.
 */
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

/** The rerank leg's own block: same rule as above, its own shape (no `emits_sparse` there). */
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

/** The file owns nothing, so every value below is the effective config.yaml / env one. */
function renderWith(config: Partial<RagConfigValues>) {
  hooks.view = {
    config: { video: null, ...config },
    sources: {},
    embedding_providers: EMBEDDING_PROVIDERS,
    rerank_providers: RERANK_PROVIDERS,
  } as RagConfigView;
  return render(<FunctionalModelsView />);
}

const labelCount = (label: string) => screen.queryAllByLabelText(label).length;

/** Mirrors the `KEYS` proxy's shape for the count-taking keys (`advancedSettings(5)`). */
const advancedLabel = (count: number) => `advancedSettings(${count})`;

/** The advanced disclosure is closed by default; its rows only exist once it opens. */
function openAdvanced() {
  fireEvent.click(screen.getByRole("button", { name: advancedLabel(6) }));
}

afterEach(() => {
  hooks.view = null;
  catalogues.models = [];
  catalogues.managed = [];
  cleanup();
});

/**
 * The RAG default row (spec 2026-09-23 default model D4/D5).
 *
 * Two things are structural rather than cosmetic, and this is the file that can pin them
 * cheaply: the row lives *inside* the functional view (there is no second control on the
 * section title), and its candidates come from the same catalogue the extraction and judge
 * rows use — `useModels()` over `modelReferenceOptions()` — not from the vision-filtered
 * managed list the caption row reads.
 */
describe("RAG default row", () => {
  /** A functional view seeding one stored default, with both catalogues pointing elsewhere. */
  function renderDefaultRow(value: string | null) {
    return renderWith({ default_model: value } as Partial<RagConfigValues>);
  }

  it("offers the chat catalogue's entries, vision declared or not", () => {
    // The default feeds all four roles, and extraction/judge never filter by vision — so
    // neither may this row. The labelled entry declares no vision at all: under the caption
    // row's source it would be filtered out, and the stored value would survive only as the
    // raw string `modelReferenceOptions` keeps for an unknown name.
    catalogues.models = [
      { name: "deepseek-chat", display_name: "DeepSeek Chat" },
      { name: "qwen-max", display_name: "Qwen Max" },
    ];

    renderDefaultRow("qwen-max");

    expect(screen.getByLabelText("defaultModel").textContent).toContain("Qwen Max");
  });

  it("labels a configured entry by its display name, not by the raw id", () => {
    // The discriminator: `modelReferenceOptions` labels a *configured* entry with its
    // display name and labels an unknown stored value with the raw string. The managed
    // catalogue below holds a different set, so a row reading it would print the id.
    catalogues.models = [
      { name: "deepseek-chat", display_name: "DeepSeek Chat" },
    ];
    catalogues.managed = [
      { name: "claude-model", display_name: "Claude X", supports_vision: true },
    ];

    renderDefaultRow("deepseek-chat");

    expect(screen.getByLabelText("defaultModel").textContent).toContain(
      "DeepSeek Chat",
    );
  });

  it("keeps a stored value that names no entry instead of clearing it", () => {
    catalogues.models = [{ name: "deepseek-chat", display_name: "DeepSeek Chat" }];

    renderDefaultRow("gone-model");

    // Opening the form must not silently drop a value the admin saved earlier.
    expect(screen.getByLabelText("defaultModel").textContent).toContain(
      "gone-model",
    );
  });

  it("shows the none label when nothing declares a default and no model exists", () => {
    renderDefaultRow(null);

    expect(screen.getByLabelText("defaultModel").textContent).toContain(
      "defaultModelNone",
    );
  });

  it("sits above the role rows, under its own label", () => {
    catalogues.models = [{ name: "deepseek-chat", display_name: "DeepSeek Chat" }];

    renderDefaultRow("deepseek-chat");

    // D4's sketch puts it first, before the existing settings — so it must precede every
    // role row in document order, and carry its own label rather than borrowing one.
    const row = screen.getByLabelText("defaultModel");
    const extraction = screen.getByLabelText("extractModel");
    expect(labelCount("defaultModel")).toBe(1);
    expect(
      row.compareDocumentPosition(extraction) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("only drafts the pick — saving stays the Save button's job", () => {
    // The Radix dropdown cannot be driven under happy-dom (the other view tests pin the
    // trigger's text for the same reason), so this rule is pinned where it lives: the row's
    // handler writes the draft, and the view keeps exactly one save call site.
    const source = readFileSync(
      path.join(FRONTEND_ROOT, "src/components/workspace/settings/functional-models-view.tsx"),
      "utf8",
    );

    expect(source).toContain('update("default_model"');
    expect(source.match(/save\.mutate\(/g)).toHaveLength(1);
  });
});

describe("provider rows", () => {
  it("keeps both endpoint rows editable and offers the vendor default as a placeholder only", () => {
    // Spec 2026-09-25 rag-endpoint-unlock: no lock and no restore-to-default — the same vendor
    // may serve different addresses (Bailian workspace-scoped endpoints), so the rows are always
    // editable and the default endpoint is only a grey hint (never a value).
    renderWith({ embedding_provider: "dashscope", rerank_provider: "dashscope" });

    expect(labelCount("embeddingBaseUrl")).toBe(1);
    expect(labelCount("rerankBaseUrl")).toBe(1);
    expect(screen.queryAllByText("lockedByProvider").length).toBe(0);
    expect(
      screen.getAllByPlaceholderText("https://dashscope.aliyuncs.com").length,
    ).toBe(2);
    expect(screen.queryAllByText("https://dashscope.aliyuncs.com").length).toBe(
      0,
    );
    expect(
      screen.queryAllByRole("button", { name: "resetToDefault" }).length,
    ).toBe(0);

    // Sparse settings defer to the disclosure, and start locked (source = provider) —
    // the endpoint unlock leaves the other locked rows alone.
    expect(labelCount("embeddingSparseSource")).toBe(0);
    openAdvanced();
    expect(labelCount("embeddingSparseSource")).toBeGreaterThan(0);
    expect(screen.getAllByText("lockedExternalOnly").length).toBe(4);
  });

  it("shows the example placeholder for a provider without a default endpoint", () => {
    renderWith({
      embedding_provider: "openai-compatible",
      rerank_provider: "generic-rerank",
    });

    expect(labelCount("embeddingBaseUrl")).toBeGreaterThan(0);
    expect(labelCount("rerankBaseUrl")).toBeGreaterThan(0);
    // No locked endpoint row remains once both providers need an address.
    expect(screen.queryByText("lockedByProvider")).toBeNull();
    expect(
      screen.getAllByPlaceholderText("https://api.example.com/v1").length,
    ).toBe(2);
  });

  it("unlocks the sparse rows when the source is a separate service", () => {
    renderWith({ embedding_sparse_source: "external" });
    openAdvanced();

    expect(labelCount("sparseBaseUrl")).toBeGreaterThan(0);
    expect(labelCount("sparseModel")).toBeGreaterThan(0);
    expect(labelCount("sparseApiKey")).toBeGreaterThan(0);
    expect(screen.queryByText("lockedExternalOnly")).toBeNull();
  });

  it("explains why the sparse model is asked for but never sent", () => {
    renderWith({ embedding_sparse_source: "external" });
    openAdvanced();

    // The value is stored in `rag_config.json` but never reaches the service: TEI serves one model
    // per instance, so no model field is sent at all (deerflow/knowledge/sparse.py). The row owes
    // the admin that sentence — an input whose effect nobody can explain is worse than no input.
    // Exactly one: the note belongs to this row, and 「稀疏」 is not repeated down the gutter.
    expect(labelCount("sparseModelHint")).toBe(1);
  });

  it("asks the sparse service the same four questions as the embedding one", () => {
    renderWith({ embedding_sparse_source: "external" });
    openAdvanced();

    // Nested under 稀疏向量来源 and named exactly like the retrieval pair, in the same order.
    // 「稀疏」 used to be repeated on every row to say what the indent now says (2026-09-16).
    const panel = document.querySelector('[data-slot="collapsible-content"]')!;
    const rows = Array.from(panel.firstElementChild!.children).map((row) =>
      row.firstElementChild?.textContent?.trim(),
    );
    expect(rows).toEqual([
      // 维度在上（spec 2026-09-26 D5-4）：它是这块最重的一项，库宽连着全库重建。
      "dimensionLabel",
      "embeddingSparseSource",
      "providerLabel",
      "modelLabel",
      "apiKeyLabel",
      "endpointLabel",
    ]);

    // The visible names are shared, so the controls carry their own to stay distinguishable.
    for (const field of [
      "sparseProvider",
      "sparseModel",
      "sparseApiKey",
      "sparseBaseUrl",
    ]) {
      expect(labelCount(field)).toBeGreaterThan(0);
    }
  });

  it("keeps the MinerU token while parsing stays on the cloud API", () => {
    renderWith({ parse_provider: "mineru-cloud" });
    openAdvanced();

    expect(labelCount("mineruToken")).toBeGreaterThan(0);
    // The cloud leg reads the address too (① 乙) and owns the two parse knobs — all editable.
    expect(labelCount("parseBaseUrl")).toBeGreaterThan(0);
    expect(labelCount("parseLanguage")).toBeGreaterThan(0);
    expect(labelCount("parseModelVersion")).toBeGreaterThan(0);
    // 云腿留空＝官方端点：字段自己用灰字说出去向（与 embedding/rerank 地址行同形状，
    // 2026-09-30 交付后调整）。
    expect(
      screen.getByLabelText("parseBaseUrl").getAttribute("placeholder"),
    ).toBe("https://mineru.net");
    // Only the local-only tier is shown locked: "local service only".
    expect(labelCount("parseTier")).toBe(0);
    expect(screen.getAllByText("lockedLocalOnly").length).toBe(1);
  });

  it("swaps the token for the service address when parsing goes local", () => {
    renderWith({ parse_provider: "mineru-local" });
    openAdvanced();

    expect(labelCount("mineruToken")).toBe(0);
    expect(labelCount("parseBaseUrl")).toBeGreaterThan(0);
    // 本地分支没有默认值：不摆任何灰字，免得被读成"默认就是它"。
    expect(
      screen.getByLabelText("parseBaseUrl").getAttribute("placeholder"),
    ).toBeNull();
    expect(labelCount("parseTier")).toBeGreaterThan(0);
    // The cloud-only rows are present as locked twins, never hidden: the token and the
    // two parse knobs.
    expect(labelCount("parseLanguage")).toBe(0);
    expect(labelCount("parseModelVersion")).toBe(0);
    expect(screen.getAllByText("lockedCloudOnly").length).toBe(3);
  });
});

/**
 * Shrinkable-row rules (spec 2026-09-24 settings-responsive-layout §4 1-2):
 *
 * 1. Row tracks are `minmax(0,1fr)`, so a squeezed column collapses instead of pushing its
 *    sibling out of the card (a bare `1fr` track floors at the child's min-content width).
 * 2. Every wrapper that sits directly on a row may collapse (`min-w-0`) — the input's own
 *    `min-w-0` cannot save a wrapper that still reports min-content.
 */
describe("shrinkable rows", () => {
  const rowOf = (el: HTMLElement) =>
    el.closest<HTMLElement>('div[class*="grid-cols-[8rem_"]')!;
  const trackCount = (row: HTMLElement) =>
    row.className.match(/minmax\(0,1fr\)/g)?.length ?? 0;

  it("pair rows carry two shrinkable tracks, single rows one", () => {
    renderWith({
      embedding_provider: "openai-compatible",
      rerank_provider: "generic-rerank",
      embedding_sparse_source: "external",
    });

    expect(trackCount(rowOf(screen.getByLabelText("embeddingModel")))).toBe(2);

    openAdvanced();
    expect(trackCount(rowOf(screen.getByLabelText("sparseModel")))).toBe(1);
  });

  it("grid children may collapse: secret wrapper, address wrapper, select triggers", () => {
    renderWith({ embedding_sparse_source: "external" });

    expect(
      screen.getByLabelText("embeddingApiKey").parentElement!.className,
    ).toContain("min-w-0");
    expect(
      screen.getByRole("combobox", { name: "embeddingProvider" }).className,
    ).toContain("min-w-0");

    openAdvanced();
    expect(
      screen.getByLabelText("sparseBaseUrl").parentElement!.className,
    ).toContain("min-w-0");
  });
});

/**
 * Narrow stacking (spec 2026-09-24 settings-responsive-layout §3.2, D1/D2/D3 甲):
 * below `lg` a two-value row stacks two self-describing lines — bold role short name
 * (the wide column heading's own word) + the shared label + the value. The shared gutter
 * label hides there and the role-heading row hides with it. At `lg` and up nothing moves.
 */
describe("narrow stacking", () => {
  const rowOf = (el: HTMLElement) =>
    el.closest<HTMLElement>('div[class*="grid-cols-[8rem_"]')!;

  it("regroups into one role block per column below md", () => {
    renderWith({});

    // The four rows go `contents` so their cells regroup under the block heads via `order`.
    const row = rowOf(screen.getByLabelText("embeddingModel"));
    expect(row.className).toContain("max-md:contents");

    // One bold block head per role (the wide heading's own word), narrow-only.
    for (const role of ["embeddingModel", "rerankModel"] as const) {
      const heads = screen
        .getAllByText(role)
        .filter((el) => el.className.includes("md:hidden"));
      expect(heads.length).toBe(1);
    }

    // Exactly one divider between the two blocks.
    const dividers = document.querySelectorAll<HTMLElement>(
      'div[class*="border-t"][class*="md:hidden"]',
    );
    expect(dividers.length).toBe(1);

    // Each cell's line head is the shared field label only — no role prefix per line.
    const cells = Array.from(row.children).slice(1) as HTMLElement[];
    expect(cells[0]!.className).toContain("order-3");
    expect(cells[1]!.className).toContain("order-9");
    for (const cell of cells) {
      expect(cell.className).toContain("md:contents");
      const copy = cell.firstElementChild as HTMLElement;
      expect(copy.textContent).toBe("modelLabel");
    }
  });

  it("single rows stack label-above-value below md", () => {
    renderWith({ embedding_sparse_source: "external" });
    openAdvanced();

    expect(rowOf(screen.getByLabelText("sparseModel")).className).toContain(
      "max-md:grid-cols-1",
    );
  });

  it("keeps the wide role-heading row hidden below md and drops the English pills", () => {
    renderWith({});

    // 标题现在是按钮（D5-5 的连通点），所以按 data-slot 选，不再按 span+类名。
    const heading = screen.getByRole("button", { name: /embeddingModel/ });
    expect(heading.parentElement!.className).toContain("max-md:hidden");

    // 乙 (spec §3.2 revision): the pills are gone everywhere, wide included.
    expect(screen.queryByText("roleTagEmbedding")).toBeNull();
    expect(screen.queryByText("roleTagRerank")).toBeNull();
  });
});

describe("wiki and synthesis rows", () => {
  it("adds one row to each existing card instead of opening a new one", () => {
    catalogues.models = [
      { name: "deepseek-chat", display_name: "DeepSeek Chat" },
    ];

    renderWith({
      extract_model: "deepseek-chat",
      judge_model: "deepseek-chat",
      wiki_model: "deepseek-chat",
      synthesis_model: "deepseek-chat",
    });

    // One row each, and each explains itself in place rather than borrowing the card's ⓘ.
    expect(labelCount("wikiModel")).toBe(1);
    expect(labelCount("synthesisModel")).toBe(1);
    expect(labelCount("wikiModelHint")).toBe(1);
    expect(labelCount("synthesisModelHint")).toBe(1);

    // ②'s decision: no new cards exist for them.
    expect(screen.queryByText("groupWiki")).toBeNull();
    expect(screen.queryByText("groupSynthesis")).toBeNull();

    // The teeth of that decision: each new row lives in the *same* card as the row it joins.
    const cardOf = (label: string) =>
      screen.getByLabelText(label).closest('[data-slot="card"]');
    expect(cardOf("wikiModel")).toBe(cardOf("extractModel"));
    expect(cardOf("synthesisModel")).toBe(cardOf("judgeModel"));

    // …and each row follows its card's existing row, in document order.
    const order = [
      "extractModel",
      "wikiModel",
      "judgeModel",
      "synthesisModel",
    ].map((label) => screen.getByLabelText(label));
    for (let i = 1; i < order.length; i += 1) {
      expect(
        order[i - 1]!.compareDocumentPosition(order[i]!) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }
  });

  it("offers a non-vision entry on both rows (no vision filter here)", () => {
    // `visionReferenceOptions` would drop this entry; the discriminator is the *display name*,
    // because a filtered-out stored value still renders as its raw name (門 A's Task 4 lesson).
    catalogues.models = [{ name: "text-only", display_name: "Text Only" }];

    renderWith({ wiki_model: "text-only", synthesis_model: "text-only" });

    expect(screen.getByLabelText("wikiModel").textContent).toContain(
      "Text Only",
    );
    expect(screen.getByLabelText("synthesisModel").textContent).toContain(
      "Text Only",
    );
  });
});
