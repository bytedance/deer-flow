/**
 * 考题详情 drawer 契约测试（2026-08-27 spec §4.5，plan Task 6；2026-09-08
 * 裸奔退役重设计；2026-10-06 改锚对升级）：
 * - 读态：字段全量渲染（query 作 sticky 头标题 / 分类 badge / 参考答案卡 /
 *   依据按文档分组 + 稳定序号徽章 / 实体卡）、无参考答案降级、复现/删除回调；
 * - 锚定可见（spec §2①/②）：逐片只读 ChunkCard（正文预览，无编辑动作回调）
 *   + 悬空片单行警示（一次 listChunksByIds 两用：请求集 − 返回集 = 悬空）；
 *   片级折叠（甲）：默认收起显 chunkPreview 摘要行，触发行展开落整卡；
 * - 改锚（spec §2③ B′）：编辑保存被锚定核验拦下 → 红块变出「仍要保存」且
 *   **不落库**（原「保存」盲重复点恒不带 anchor_ack，wire 级断言）；「仍要
 *   保存」携 anchor_ack=true 落库；missing_chunk 无确认钮；清空勾选 = 解除
 *   锚定；组头「已选 n/N」实时；组内分页 50/页加载更多。
 *
 * 只 mock 共享 fetcher（CSRF 面）与 sonner——hooks/api/useAnchorConfirm 全真，
 * ack 语义钉在真实请求体上（盲双击不落库的物理保证）。
 */
import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";

const fetchMock = rs.hoisted(() => ({ fetch: rs.fn() }));

rs.mock("@/core/api/fetcher", () => fetchMock);

rs.mock("sonner", () => ({
  toast: { error: rs.fn(), success: rs.fn(), info: rs.fn(), warning: rs.fn() },
}));

import { EvalQuestionDrawer } from "@/components/workspace/knowledge/eval-question-drawer";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type {
  AnchorBlockDetail,
  EvalQuestion,
  KnowledgeChunk,
  KnowledgeChunkWithDoc,
  KnowledgeDocument,
} from "@/core/knowledge/types";

const DOC_A = "a".repeat(32);
const DOC_B = "b".repeat(32);
const DOC_C = "c".repeat(32);

const CHUNK_A = `${DOC_A}#0001`;
const CHUNK_B = `${DOC_B}#0002`;
const CHUNK_C = `${DOC_C}#0003`;

const Q_ANCHORED: EvalQuestion = {
  id: "q_22222222",
  query: "锚定了三个切片的考题",
  category: "fact",
  expected_paths: ["vector"],
  relevant_chunk_ids: [CHUNK_A, CHUNK_B, CHUNK_C],
  relevant_entities: ["退休", "养老金"],
  reference_answer: "参考答案全文。",
};

const Q_UNANCHORED: EvalQuestion = {
  id: "q_11111111",
  query: "未锚定的考题",
  category: "global",
  expected_paths: ["wiki"],
  relevant_chunk_ids: [],
  relevant_entities: [],
  reference_answer: null,
};

const Q_MULTI: EvalQuestion = {
  id: "q_33333333",
  query: "多路预期的考题",
  category: "relation",
  expected_paths: ["vector", "graph"],
  relevant_chunk_ids: [CHUNK_A],
  relevant_entities: [],
  reference_answer: null,
};

function doc(id: string, name: string, chunkCount: number): KnowledgeDocument {
  return {
    id,
    kb_id: "kb-1",
    uploader_id: "user-1",
    name,
    size_bytes: 100,
    storage_path: "p",
    status: "ready",
    progress_percent: 100,
    chunk_count: chunkCount,
    error: null,
    path_status: null,
    content_hash: null,
    created_at: "2026-10-06T09:00:00Z",
  };
}

function chunk(chunkId: string, text: string, docName: string): KnowledgeChunkWithDoc {
  return {
    chunk_id: chunkId,
    doc_id: chunkId.split("#")[0]!,
    kb_id: "kb-1",
    chunk_index: 0,
    text,
    heading_path: [],
    page: null,
    token_count: 8,
    entities: [],
    extract_status: "done",
    last_edited_at: null,
    doc_name: docName,
  };
}

const BLOCK_DETAIL: AnchorBlockDetail = {
  reason: "mismatch",
  miss_terms: ["装箱"],
  hits: 1,
  best_hits: 3,
  suggested_chunk: "abc#0001",
};

// ── fetch 路由（真实 api/hooks 打在共享 fetcher 上）────────────────────────
interface FetchState {
  docs: KnowledgeDocument[];
  chunksByIds: KnowledgeChunkWithDoc[];
  docPages: Record<string, { items: KnowledgeChunk[]; total: number }>;
  updateResponses: Response[];
}

const state: FetchState = {
  docs: [],
  chunksByIds: [],
  docPages: {},
  updateResponses: [],
};

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function routeFetch(url: string, init?: RequestInit): Response {
  const method = init?.method ?? "GET";
  if (url.includes("/eval/questions/") && method === "PATCH") {
    return state.updateResponses.shift() ?? jsonResponse(200, Q_ANCHORED);
  }
  const pageMatch = /\/documents\/([^/]+)\/chunks\?/.exec(url);
  if (pageMatch) {
    const page = state.docPages[pageMatch[1]!] ?? { items: [], total: 0 };
    return jsonResponse(200, { items: page.items, total: page.total, offset: 0, limit: 50 });
  }
  if (url.includes("/chunks?")) return jsonResponse(200, { items: state.chunksByIds });
  if (url.endsWith("/documents")) return jsonResponse(200, state.docs);
  return jsonResponse(404, { detail: `unrouted fetch: ${url}` });
}

/** PATCH 请求体（wire 级 ack 断言：原按钮永不带真值 anchor_ack）。 */
function patchBodies(): Record<string, unknown>[] {
  return fetchMock.fetch.mock.calls
    .filter((call) => (call[1] as RequestInit | undefined)?.method === "PATCH")
    .map((call) => JSON.parse((call[1] as RequestInit).body as string) as Record<string, unknown>);
}

function renderDrawer(question: EvalQuestion, onReproduce?: (q: string) => void) {
  const onDelete = rs.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <I18nContext.Provider value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}>
        <EvalQuestionDrawer
          kbId="kb-1"
          onDelete={onDelete}
          onOpenChange={() => undefined}
          onReproduce={onReproduce}
          open
          question={question}
        />
      </I18nContext.Provider>
    </QueryClientProvider>,
  );
  return onDelete;
}

beforeEach(() => {
  fetchMock.fetch.mockReset();
  fetchMock.fetch.mockImplementation((input: unknown, init?: RequestInit) =>
    Promise.resolve(routeFetch(String(input), init)),
  );
  state.docs = [doc(DOC_A, "文档甲", 2), doc(DOC_B, "文档乙", 1), doc(DOC_C, "文档丙", 1)];
  state.chunksByIds = [];
  state.docPages = {};
  state.updateResponses = [];
});

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("EvalQuestionDrawer 读态", () => {
  it("字段全量渲染：query 全文、分类 badge、参考答案、依据按文档分组", async () => {
    renderDrawer(Q_ANCHORED);
    expect(screen.getByText(Q_ANCHORED.query)).toBeTruthy();
    expect(screen.getByText("事实")).toBeTruthy();
    // 依据分组（2026-09-07）：组头=文档标题（取不到回退 doc_id 前 8 位），
    // 组内=chunk id 稳定序号；32 位 hex 裸 ID 不再出现。
    expect(await screen.findByText("文档甲")).toBeTruthy();
    expect(await screen.findByText("文档乙")).toBeTruthy();
    expect(await screen.findByText("文档丙")).toBeTruthy();
    expect(screen.getByText("#0001")).toBeTruthy();
    expect(screen.getByText("#0002")).toBeTruthy();
    expect(screen.getByText("#0003")).toBeTruthy();
    expect(screen.queryByText(CHUNK_A)).toBeNull();
    expect(screen.getByText("退休")).toBeTruthy();
    expect(screen.getByText("参考答案全文。")).toBeTruthy();
    // 悬浮统一（2026-10-06）：参考文档组头原生 title 换项目 Tooltip。
    expect(screen.getByText("文档甲").getAttribute("title")).toBeNull();
    // 容器化（2026-09-08 裸奔退役）：分区卡 caption 进卡内分组头，切片
    // 计数徽章（下钻层「N 切片」词汇）。
    expect(screen.getByText("参考答案")).toBeTruthy();
    expect(screen.getByText("参考文档")).toBeTruthy();
    expect(screen.getByText("实体")).toBeTruthy();
    expect(screen.getByText("3 切片")).toBeTruthy();
  });

  it("无锚定与无参考答案的降级渲染", () => {
    renderDrawer(Q_UNANCHORED);
    expect(screen.getByText("未填写")).toBeTruthy();
    expect(screen.getByText("未锚定")).toBeTruthy();
    // 实体卡仅有值显：空标注诚实缺省不摆空卡（也不显计数徽章）。
    expect(screen.queryByText("实体")).toBeNull();
  });

  it("多路预期渲染全量路径 Badge（与题库表格同口径）", () => {
    renderDrawer(Q_MULTI);
    expect(screen.getByText("vector")).toBeTruthy();
    expect(screen.getByText("graph")).toBeTruthy();
  });

  it("复现按钮回调携带 query；删除按钮回调携带该题", () => {
    const onReproduce = rs.fn();
    const onDelete = renderDrawer(Q_ANCHORED, onReproduce);
    fireEvent.click(screen.getByRole("button", { name: "在召回测试面板复现" }));
    expect(onReproduce).toHaveBeenCalledWith(Q_ANCHORED.query);
    fireEvent.click(screen.getByRole("button", { name: "删除考题" }));
    expect(onDelete).toHaveBeenCalledWith(Q_ANCHORED);
  });

  // ── ① 锚定可见 + 悬空徽章（2026-10-06 spec §2①/②）+ 片级折叠（甲）──
  it("逐片只读 ChunkCard：默认收起显摘要行，展开落整卡 + 悬空片单行警示（请求集 − 返回集）", async () => {
    // 一次 listChunksByIds 两用：CHUNK_C 静默缺失 → 悬空。
    state.chunksByIds = [
      chunk(CHUNK_A, "切片一摘要行\n\n切片一长正文第二段", "文档甲"),
      chunk(CHUNK_B, "切片二摘要行\n\n切片二长正文第二段", "文档乙"),
    ];
    renderDrawer(Q_ANCHORED);

    // 默认全收起（甲）：摘要行（chunkPreview 同编辑勾选区口径）在、正文不在。
    expect(await screen.findByText("切片一摘要行")).toBeTruthy();
    expect(screen.getByText("切片二摘要行")).toBeTruthy();
    expect(screen.queryByText("切片一长正文第二段")).toBeNull();
    expect(screen.queryByText("切片二长正文第二段")).toBeNull();

    // 展开后 ChunkCard 整卡落下（正文可见）；只读 = 不传 onEdit/onDelete/
    // onReExtract：切片卡无编辑动作（「编辑锚定」入口是另一根轴）。
    fireEvent.click(screen.getByRole("button", { name: /#0001/ }));
    expect(await screen.findByText("切片一长正文第二段")).toBeTruthy();
    expect(screen.queryByText(zhCN.knowledge.chunkDrawer.delete)).toBeNull();
    expect(screen.queryByText(zhCN.knowledge.chunkDrawer.edit)).toBeNull();
    expect(screen.getByRole("button", { name: "编辑锚定" })).toBeTruthy();

    // 悬空片（CHUNK_C）：序号徽章 + 「悬空」词的破坏性警示行，无正文卡、
    // 无折叠触发行（没有内容可折）。
    expect(screen.getByText("悬空")).toBeTruthy();
    expect(screen.getByText("#0003")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /#0003/ })).toBeNull();
  });

  it("片折叠往返：触发行 aria-expanded 翻转，收起即正文让位回摘要行", async () => {
    state.chunksByIds = [chunk(CHUNK_A, "切片一摘要行\n\n切片一长正文第二段", "文档甲")];
    renderDrawer(Q_MULTI);

    const trigger = await screen.findByRole("button", { name: /#0001/ });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(await screen.findByText("切片一长正文第二段")).toBeTruthy();
    // 再点收起：正文卸载，摘要行回来（内容不悬空占位）。
    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    await waitFor(() => {
      expect(screen.queryByText("切片一长正文第二段")).toBeNull();
    });
    expect(screen.getByText("切片一摘要行")).toBeTruthy();
  });

  it("疑片行「存疑」徽章（spec §2④）：触发行上随行可见 + 同款 Tooltip 机器依据", async () => {
    state.chunksByIds = [chunk(CHUNK_A, "切片一摘要行\n\n切片一长正文第二段", "文档甲")];
    renderDrawer({
      ...Q_MULTI,
      anchor_mismatch: {
        reason: "zero_hit",
        miss_terms: ["装箱"],
        hits: 0,
        best_hits: 3,
        suggested_chunk: CHUNK_B,
        chunk_ids: [CHUNK_A],
      },
    });

    // 徽章在触发行上（默认收起也可见，不藏进展开区）。
    const trigger = await screen.findByRole("button", { name: /#0001/ });
    expect(trigger.textContent).toContain("存疑");
    // 悬浮/聚焦触发行 → 项目 Tooltip 机器依据（红块同款文案）。
    fireEvent.focus(trigger);
    const tooltips = await screen.findAllByRole("tooltip");
    const evidence = tooltips.map((node) => node.textContent ?? "").join("\n");
    expect(evidence).toContain("缺失术语");
    expect(evidence).toContain("建议锚");
  });

  it("悬空警示仅在取数返回后出现（缺片差额口径，不看 missing_chunk_ids 字段）", async () => {
    state.chunksByIds = [chunk(CHUNK_A, "切片正文一：装箱与拆箱", "文档甲")];
    // missing_chunk_ids 有值但取数齐全的 id 也照差额走：本例 CHUNK_B/CHUNK_C
    // 都缺 → 两行警示；字段只喂行级徽章（bank），抽屉判定同源于取数差额。
    renderDrawer({ ...Q_ANCHORED, missing_chunk_ids: [CHUNK_C] });
    await screen.findByText("切片正文一：装箱与拆箱");
    expect(screen.getAllByText("悬空")).toHaveLength(2);
  });
});

describe("EvalQuestionDrawer 改锚（B′）", () => {
  function enterEdit() {
    fireEvent.click(screen.getByRole("button", { name: "编辑锚定" }));
  }

  // ── ②③ 保存被拦不落库 + 确认钮携 anchor_ack=true（wire 级）────────────
  it("编辑保存被拦落红块（无错误 toast），原「保存」重提恒无 ack，「仍要保存」携 anchor_ack=true 落库", async () => {
    state.docPages = { [DOC_A]: { items: [chunk(CHUNK_A, "甲片一正文", "文档甲")], total: 1 } };
    state.updateResponses = [
      jsonResponse(422, { detail: BLOCK_DETAIL }),
      jsonResponse(422, { detail: BLOCK_DETAIL }),
      jsonResponse(200, { ...Q_MULTI, relevant_chunk_ids: [] }),
    ];
    renderDrawer(Q_MULTI);
    enterEdit();

    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    const block = await screen.findByRole("alert");
    expect(block.textContent).toContain("装箱");
    expect(screen.getByRole("button", { name: "仍要保存" })).toBeTruthy();
    expect(rs.mocked(toast.error)).not.toHaveBeenCalled();
    // 首击虽已问过机器核验（422 即机器证据来源），但请求体根本不带
    // anchor_ack 键——确认标记物理缺席，不落库。
    expect(patchBodies()).toHaveLength(1);
    expect(patchBodies()[0]).not.toHaveProperty("anchor_ack");
    // 编辑区仍在（保存未完成）。
    expect(screen.getByRole("button", { name: "保存" })).toBeTruthy();

    // 原按钮盲重复点：仍是无确认重提（盲双击 ≠ 看见）。
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() => expect(patchBodies()).toHaveLength(2));
    expect(patchBodies()[1]).not.toHaveProperty("anchor_ack");

    // 红块内「仍要保存」→ anchor_ack=true → 落库并收尾（编辑区关闭）。
    fireEvent.click(screen.getByRole("button", { name: "仍要保存" }));
    await waitFor(() => expect(patchBodies()).toHaveLength(3));
    expect(patchBodies()[2]?.anchor_ack).toBe(true);
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "保存" })).toBeNull();
    });
    // 提交体只动锚（relevant_chunk_ids）。
    expect(patchBodies()[2]?.relevant_chunk_ids).toEqual([CHUNK_A]);
    expect(patchBodies()[2]).not.toHaveProperty("query");
    expect(patchBodies()[2]).not.toHaveProperty("reference_answer");
  });

  it("missing_chunk 红块渲染但无确认钮（不可绕过）", async () => {
    state.docPages = { [DOC_A]: { items: [chunk(CHUNK_A, "甲片一正文", "文档甲")], total: 1 } };
    state.updateResponses = [
      jsonResponse(422, {
        detail: { reason: "missing_chunk", miss_terms: [], hits: 0, best_hits: 0, suggested_chunk: null },
      }),
    ];
    renderDrawer(Q_MULTI);
    enterEdit();

    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    const block = await screen.findByRole("alert");
    expect(block.textContent).toContain(zhCN.knowledge.eval.anchorBlock.missing);
    expect(screen.queryByRole("button", { name: "仍要保存" })).toBeNull();
    expect(rs.mocked(toast.error)).not.toHaveBeenCalled();
    expect(patchBodies()[0]).not.toHaveProperty("anchor_ack");
  });

  it("清空勾选 = 解除锚定（提交空数组合法）", async () => {
    state.docPages = { [DOC_A]: { items: [chunk(CHUNK_A, "甲片一正文", "文档甲")], total: 1 } };
    state.updateResponses = [jsonResponse(200, { ...Q_MULTI, relevant_chunk_ids: [] })];
    renderDrawer(Q_MULTI);
    enterEdit();

    // 已锚片默认勾上；取消勾选即出锚定集。
    const row = await screen.findByRole("checkbox", { name: /甲片一正文/ });
    expect(row.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(row);
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => expect(patchBodies()).toHaveLength(1));
    expect(patchBodies()[0]?.relevant_chunk_ids).toEqual([]);
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "保存" })).toBeNull();
    });
  });

  // ── 折叠分组勾选区（spec §2③ D3 细则）────────────────────────────────
  it("按文档折叠分组：含已锚文档默认展开、其余收起；组头「已选 n/N」实时", async () => {
    state.docPages = {
      [DOC_A]: {
        items: [chunk(CHUNK_A, "甲片一正文", "文档甲"), chunk(`${DOC_A}#0004`, "甲片二正文", "文档甲")],
        total: 2,
      },
    };
    renderDrawer(Q_MULTI);
    enterEdit();

    // 含已锚片的文档默认展开；无锚文档默认收起。
    expect((await screen.findByRole("button", { name: /文档甲/ })).getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("button", { name: /文档乙/ }).getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByRole("button", { name: /文档丙/ }).getAttribute("aria-expanded")).toBe("false");
    // 组头计数：已锚 1 片 / 共 2 片。
    expect(screen.getByText("已选 1/2")).toBeTruthy();

    // 勾选变化计数实时；整组可随时收起（计数留在组头）。
    fireEvent.click(await screen.findByRole("checkbox", { name: /甲片二正文/ }));
    expect(screen.getByText("已选 2/2")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /文档甲/ }));
    expect(screen.getByRole("button", { name: /文档甲/ }).getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByText("已选 2/2")).toBeTruthy();
  });

  it("组内分页 50/页：还有余量出「加载更多」，续拉 offset=已加载数", async () => {
    const page1 = Array.from({ length: 3 }, (_, index) =>
      chunk(`${DOC_A}#${String(index + 1).padStart(4, "0")}`, `甲片${index + 1}正文`, "文档甲"),
    );
    state.docPages = { [DOC_A]: { items: page1, total: 5 } };
    renderDrawer(Q_MULTI);
    enterEdit();

    await screen.findByRole("checkbox", { name: /甲片1正文/ });
    const more = screen.getByRole("button", { name: "加载更多" });

    // 续页返回 2 片 → 加载完按钮消失（total 对齐）。
    state.docPages[DOC_A] = {
      items: [chunk(`${DOC_A}#0004`, "甲片4正文", "文档甲"), chunk(`${DOC_A}#0005`, "甲片5正文", "文档甲")],
      total: 5,
    };
    fireEvent.click(more);
    expect(await screen.findByRole("checkbox", { name: /甲片5正文/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "加载更多" })).toBeNull();
    // 分页请求：50 片/页，offset = 已加载数（首页 0、续页 3）。
    const docPageUrls = fetchMock.fetch.mock.calls
      .map((call) => String(call[0]))
      .filter((url) => /\/documents\/[^/]+\/chunks\?/.test(url));
    expect(docPageUrls.some((url) => url.includes("offset=0") && url.includes("limit=50"))).toBe(true);
    expect(docPageUrls.some((url) => url.includes("offset=3") && url.includes("limit=50"))).toBe(true);
  });

  it("编辑态悬空锚单列可摘除行（否则悬空题死锁：草稿含缺片、missing_chunk 恒拦）", async () => {
    // CHUNK_C 悬空（取数静默缺它）；选片区须给它一行（序号徽章 + 「悬空」+
    // 勾选框），摘除后提交体不含该片。缺这行 = 悬空锚在草稿里无从去掉。
    state.chunksByIds = [
      chunk(CHUNK_A, "甲片一正文", "文档甲"),
      chunk(CHUNK_B, "乙片正文", "文档乙"),
    ];
    state.docPages = {
      [DOC_A]: { items: [chunk(CHUNK_A, "甲片一正文", "文档甲")], total: 1 },
      [DOC_B]: { items: [chunk(CHUNK_B, "乙片正文", "文档乙")], total: 1 },
      [DOC_C]: { items: [], total: 0 },
    };
    state.updateResponses = [jsonResponse(200, { ...Q_ANCHORED, relevant_chunk_ids: [CHUNK_A, CHUNK_B] })];
    renderDrawer(Q_ANCHORED);
    enterEdit();

    const row = await screen.findByRole("checkbox", { name: /悬空/ });
    expect(row.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(row);
    fireEvent.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => expect(patchBodies()).toHaveLength(1));
    expect(patchBodies()[0]?.relevant_chunk_ids).toEqual([CHUNK_A, CHUNK_B]);
  });
});
