/**
 * Middle column of the knowledge page (spec §5.2/§3.6): kb header actions,
 * the document table (名称/状态/上传者/时间/大小/切片数 + 尾部悬停窄列，2026-09-02 状态提前),
 * the aggregated bottom stats row, drag-drop upload, cascade-warning delete
 * confirms, and failed-doc retry. Presentational — data/mutations arrive via props.
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { toast } from "sonner";

import {
  DocumentPanel,
  PathStatusBreakdown,
} from "@/components/workspace/knowledge/document-panel";
import { KB_TOASTER_ID } from "@/components/workspace/knowledge/kb-toast";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import { pathStatusLines } from "@/core/knowledge/path-status";
import type { KnowledgeBase, KnowledgeDocument } from "@/core/knowledge/types";

rs.mock("sonner", () => ({
  toast: { error: rs.fn(), success: rs.fn() },
}));

const KB: KnowledgeBase = {
  id: "kb-1",
  owner_id: "user-1",
  name: "产品资料",
  description: "",
  visibility: "private",
  created_at: "2026-08-09T10:00:00Z",
};

function doc(partial: Partial<KnowledgeDocument>): KnowledgeDocument {
  return {
    id: "doc-1",
    kb_id: "kb-1",
    uploader_id: "user-1",
    name: "产品手册.pdf",
    size_bytes: 2048,
    storage_path: "p",
    status: "ready",
    progress_percent: 100,
    chunk_count: 12,
    error: null,
    path_status: null,
    content_hash: null,
    created_at: "2026-08-09T10:00:00Z",
    ...partial,
  };
}

function renderPanel(props?: Partial<Parameters<typeof DocumentPanel>[0]>) {
  const handlers = {
    onUpload: rs.fn(),
    onDeleteDocument: rs.fn().mockResolvedValue(undefined),
    onRetryDocument: rs.fn(),
    onOpenChunks: rs.fn(),
  };
  render(
    <I18nContext.Provider
      value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}
    >
      <DocumentPanel
        kb={KB}
        documents={[doc({})]}
        supportedSuffixes={[".md", ".pdf", ".txt"]}
        {...handlers}
        {...props}
      />
    </I18nContext.Provider>,
  );
  return handlers;
}

afterEach(cleanup);

describe("DocumentPanel toolbar", () => {
  it("keeps the toolbar lean: search + sort only (upload/settings live in MiddleTabs)", () => {
    renderPanel();
    expect(screen.getByLabelText("搜索文档…")).toBeTruthy();
    expect(screen.getByRole("button", { name: "排序方式" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "上传文档" })).toBeNull();
    expect(screen.queryByRole("button", { name: "设置" })).toBeNull();
    expect(screen.queryByText("生成百科")).toBeNull();
  });

  it("matches the wiki tab's toolbar height (sort trigger sized to the h-7 search input)", () => {
    renderPanel();
    // icon-sm（size-8/32px）比搜索框 h-7（28px）高，会把工具栏撑高 4px——
    // 覆盖为 size-7 与 wiki tab 搜索栏行高对齐。
    const sortTrigger = screen.getByRole("button", { name: "排序方式" });
    expect(sortTrigger.className).toContain("size-7");
  });
});

describe("DocumentPanel 空态", () => {
  it("渲染九宫格文件图标：切片欢迎类型齐全、默认降调、悬停彩蛋类就位", () => {
    renderPanel({ documents: [] });
    const grid = screen.getByTestId("empty-doc-icons");
    const icons = [...grid.querySelectorAll("[data-filetype]")];
    expect(icons).toHaveLength(9);
    const kinds = icons.map((svg) => svg.getAttribute("data-filetype"));
    // 视频腿已裁（切片不接受 .mp4 上传）⇒ 九宫格不含 media，notes.md 补第九格（code 类重复）。
    for (const kind of ["pdf", "word", "sheet", "ppt", "code", "image", "archive", "unknown"]) {
      expect(kinds).toContain(kind);
    }
    expect(kinds).not.toContain("media");
    // 降噪：默认半透明；悬停恢复全彩 + 上浮（彩蛋）。
    expect(icons[0]!.className).toContain("opacity-60");
    expect(icons[0]!.className).toContain("hover:opacity-100");
    expect(icons[0]!.className).toContain("hover:-translate-y-1");
  });

  it("克制三段式只剩两段：九宫格 + 短文案，不再有上传按钮与隐藏选择器", () => {
    renderPanel({ documents: [] });
    expect(screen.getByText("上传或拖拽文件开始构建索引")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "上传文档" })).toBeNull();
    expect(screen.queryByTestId("empty-state-upload-input")).toBeNull();
  });

  it("有文档时不渲染空态", () => {
    renderPanel();
    expect(screen.queryByTestId("empty-doc-icons")).toBeNull();
  });

  it("空态锚定 ScrollArea Root 填满滚动区（absolute inset-0，2026-09-04 修居中回归）", () => {
    renderPanel({ documents: [] });
    // h-full 挂在 Viewport 内层 auto 高测量 wrapper 上会回退 auto → 塌成内容高靠上；
    // absolute inset-0 锚定 ScrollArea Root（relative）才能恢复水平+垂直居中。
    const grid = screen.getByTestId("empty-doc-icons");
    expect(grid.parentElement?.className).toContain("absolute inset-0");
  });
});

describe("DocumentPanel 拖入类型识别（九宫格双态反馈）", () => {
  function dragFiles(types: string[]) {
    const zone = screen.getByTestId("document-dropzone");
    fireEvent.dragOver(zone, {
      dataTransfer: { items: types.map((type) => ({ kind: "file", type })) },
    });
  }

  function iconsOf(kind: string) {
    return [
      ...screen.getByTestId("empty-doc-icons").querySelectorAll(`[data-filetype="${kind}"]`),
    ];
  }

  it("拖入接受类型：对应图标放大点亮，其余降灰", () => {
    renderPanel({ documents: [], supportedSuffixes: [".pdf", ".md"] });
    dragFiles(["application/pdf"]);
    const lit = iconsOf("pdf")[0]!;
    expect(lit.className).toContain("scale-125");
    expect(lit.className).toContain("opacity-100");
    expect(iconsOf("image")[0]!.className).toContain("opacity-25");
  });

  it("拖入全部不支持：九宫格整体降灰，遮罩提示格式不支持", () => {
    renderPanel({ documents: [], supportedSuffixes: [".pdf"] });
    dragFiles(["application/x-msdownload"]);
    for (const kind of ["pdf", "word", "image"]) {
      expect(iconsOf(kind)[0]!.className).toContain("opacity-25");
    }
    expect(screen.getByText("该格式暂不支持")).toBeTruthy();
  });

  it("混合拖入：接受的点亮，遮罩仍是释放以上传", () => {
    renderPanel({ documents: [], supportedSuffixes: [".pdf"] });
    dragFiles(["application/pdf", "application/zip"]);
    expect(iconsOf("pdf")[0]!.className).toContain("scale-125");
    expect(screen.getByText("释放以上传到当前知识库")).toBeTruthy();
  });

  it("离开后反馈复位：图标回到默认降调", () => {
    renderPanel({ documents: [], supportedSuffixes: [".pdf"] });
    dragFiles(["application/pdf"]);
    fireEvent.dragLeave(screen.getByTestId("document-dropzone"));
    expect(iconsOf("pdf")[0]!.className).toContain("opacity-60");
    expect(iconsOf("pdf")[0]!.className).not.toContain("scale-125");
  });

  it("在图标间穿梭不误复位：子元素冒泡的 dragleave 不触发震荡（防闪烁回归）", () => {
    renderPanel({ documents: [], supportedSuffixes: [".pdf"] });
    dragFiles(["application/pdf"]);
    // 模拟从图标 A 移到图标 B：dragleave 从子元素冒泡，relatedTarget 仍在面板内。
    // happy-dom 不认 eventInit 里的 relatedTarget，需手工注入到事件实例上。
    const from = iconsOf("pdf")[0]!;
    const to = iconsOf("word")[0]!;
    const leaveEvent = new Event("dragleave", { bubbles: true });
    Object.defineProperty(leaveEvent, "relatedTarget", { value: to });
    fireEvent(from, leaveEvent);
    // 反馈必须保持：pdf 仍点亮，遮罩仍在——否则就是逐帧震荡的闪烁。
    expect(iconsOf("pdf")[0]!.className).toContain("scale-125");
    expect(screen.getByTestId("document-drop-overlay")).toBeTruthy();
  });

  it("虚线遮罩只盖内容区：不把搜索工具栏包进框里", () => {
    renderPanel({ documents: [], supportedSuffixes: [".pdf"] });
    dragFiles(["application/pdf"]);
    const overlay = screen.getByTestId("document-drop-overlay");
    const search = screen.getByLabelText("搜索文档…");
    expect(overlay.parentElement!.contains(search)).toBe(false);
  });
});

describe("DocumentPanel table", () => {
  it("renders the six columns with formatted values（大小统一 KB：每格带 KB 后缀，2026-08-31）", () => {
    renderPanel();
    expect(screen.getByText("名称")).toBeTruthy();
    expect(screen.getByText("上传者")).toBeTruthy();
    expect(screen.getByText("大小")).toBeTruthy();
    expect(screen.getByText("切片数")).toBeTruthy();
    expect(screen.getByText("状态")).toBeTruthy();
    expect(screen.getByText("时间")).toBeTruthy();
    expect(screen.getByText("产品手册.pdf")).toBeTruthy();
    expect(screen.getByText("我")).toBeTruthy();
    // 表头不带单位，单元格自带 KB 后缀（2048B → 2 KB）；统计行总额仍用自适应单位
    expect(screen.getByTestId("doc-size-value").textContent).toBe("2 KB");
    expect(screen.getByText("12")).toBeTruthy();
    expect(screen.getByText("就绪")).toBeTruthy();
  });

  it("行间无横线：分隔靠留白+悬停底色，结构线只留表头与统计行（2026-08-31）", () => {
    renderPanel();
    // Drive/Notion 无框表风格：数据行不再带 border-b，悬停底色即行边界。
    const row = screen.getByText("产品手册.pdf").closest("tr")!;
    expect(row.className).not.toContain("border-b");
    // 吸顶表头（2026-09-02）：border-collapse 下粘性单元格的边框会随滚动丢失，
    // 故表格改 border-separate，tr 不再背 border-b。发丝线用 inset 阴影而非
    // th 的 border：border 参与盒高，会使 th 高度随复选框状态在 36.13↔36.00 间
    // 重取整、击穿 h-9 钉高（勾选行跳动复发）；阴影不参与布局。
    const table = row.closest("table")!;
    expect(table.className).toContain("border-separate");
    expect(table.className).toContain("border-spacing-0");
    const headCell = table.querySelector("thead th")!;
    expect(headCell.className).toContain("sticky");
    expect(headCell.className).toContain("top-0");
    expect(headCell.className).not.toContain("border-b");
    expect(headCell.className).toContain("shadow-[inset_0_-1px_0_var(--border)]");
    expect(headCell.className).toContain("bg-background");
    expect(table.querySelector("thead tr")!.className).not.toContain("border-b");
    // 表头行固定高度（2026-09-01）：防止全选框 unchecked↔indeterminate 切换时，
    // 折叠布局重新取整导致表头高度变化、所有行跟着上下抖动。
    expect(
      table.querySelector("thead tr")!.className,
    ).toContain("h-9");
    // 表头上方不画线（2026-09-01）：工具栏与表头间靠留白分界，避免表头被两条线夹成条状。
    const toolbar = screen.getByLabelText("搜索文档…").closest("div[class*='h-11']")!;
    expect(toolbar.className).not.toContain("border-b");
  });

  it("时间列等宽数字：tabular-nums 使 1/2 同宽，行间时分对齐（2026-08-31）", () => {
    renderPanel({
      documents: [
        doc({ id: "a", name: "早班.pdf", created_at: "2026-08-31T01:11:00Z" }),
        doc({ id: "b", name: "晚班.pdf", created_at: "2026-08-23T22:59:00Z" }),
      ],
    });
    // 比例字体下 1 比 2 窄，行间时分错位——主流表格（Gmail/Linear/金融）
    // 用 font-variant-numeric: tabular-nums 解决，不换 monospace 字体。
    for (const name of ["早班.pdf", "晚班.pdf"]) {
      const row = screen.getByText(name).closest("tr")!;
      const cells = within(row).getAllByRole("cell");
      const timeCell = cells.find((cell) =>
        /\d{4}\/\d{2}\/\d{2}/.test(cell.textContent ?? ""),
      )!;
      expect(timeCell.className).toContain("tabular-nums");
    }
  });

  it("列序：状态紧随名称（核心元数据提前）、文本列居左、数值列聚右；无操作列", () => {
    renderPanel();
    // 主流文件管理器（资源管理器/Drive）：文本列在左，大小/数量聚到右端。
    // 状态提到上传者前（2026-09-02）：状态是核心高频元数据，上传者在个人库信息量低。
    const headers = Array.from(screen.getAllByRole("columnheader"));
    expect(headers.map((h) => h.textContent?.trim())).toEqual([
      "",
      "名称",
      "状态",
      "上传者",
      "时间",
      "大小",
      "切片数",
      "",
    ]);
    // 数值列表头左对齐（与文本列一致），数值内容整体靠右——
    // Notion/Airtable 流派（2026-08-31 用户拍板，推翻表头数据同轴右对齐）。
    expect(headers[5]!.className).not.toContain("text-right");
    expect(headers[6]!.className).not.toContain("text-right");
    // 尾部窄列只承接悬停三个点：无标题、固定窄宽，平时留白不遮数值（Drive 惯例）
    expect(headers[7]!.className).toContain("w-10");
    const sizeCell = screen.getByTestId("doc-size-value").closest("td")!;
    expect(sizeCell.className).toContain("text-right");
    expect(sizeCell.className).toContain("tabular-nums");
    expect(screen.getByText("12").closest("td")!.className).toContain(
      "text-right",
    );
  });

  it("上传者列内容内缩一档：光学校正「内容看似超出表头」（2026-08-31）", () => {
    renderPanel();
    const cell = screen.getByText("我").closest("td")!;
    // 表头 12px 浅灰小字、内容 14px 深色——重墨色视觉上会「抢出来」，
    // 内容比表头多一档缩进（pl-3 vs px-2），看起来收在列内。
    expect(cell.className).toContain("pl-3");
  });

  it("renders the em-dash placeholder while chunk_count is null", () => {
    renderPanel({
      documents: [
        doc({ status: "indexing", progress_percent: 40, chunk_count: null }),
      ],
    });
    expect(screen.getByText("—")).toBeTruthy();
    // exact match pins the status badge (the stats row reads "索引中 1")
    expect(screen.getByText("索引中")).toBeTruthy();
    expect(screen.getByText(/40%/)).toBeTruthy();
  });

  it("hides the percent for pre-indexing stages (no real progress source there)", () => {
    // 2026-08-12 体验修正：待解析/解析中/切片中无可测进度（MinerU 单次调用无
    // 回调），只显示阶段徽章，不挂无信息量的 0%
    renderPanel({
      documents: [
        doc({
          status: "parsing",
          progress_percent: 0,
          chunk_count: null,
          path_status: { vector: "pending" },
        }),
      ],
    });
    expect(screen.getByText("解析中")).toBeTruthy();
    expect(screen.queryByText(/\d+%/)).toBeNull();
  });

  it("错误信息不常驻表格（产品化：失败只留状态，原因走 toast 通知，2026-08-30）", () => {
    renderPanel({
      documents: [
        doc({ status: "failed", error: "retry limit reached (5 attempts)" }),
      ],
    });
    // 原始英文不外露；表格里只剩失败状态本身（红点+文案由状态列承载）
    expect(screen.queryByText(/retry limit/)).toBeNull();
    expect(screen.getByText("失败")).toBeTruthy();
  });

  it("opens the chunk drawer when a row is clicked", () => {
    const { onOpenChunks } = renderPanel();
    fireEvent.click(screen.getByText("产品手册.pdf"));
    expect(onOpenChunks).toHaveBeenCalledWith(
      expect.objectContaining({ id: "doc-1" }),
    );
  });

  it("deletes a document after the cascade-warning confirm", async () => {
    const { onDeleteDocument } = renderPanel();
    // 删除收进尾部窄列的三个点（2026-08-31）：不再有操作列常驻按钮。
    fireEvent.keyDown(screen.getByRole("button", { name: "更多操作" }), {
      key: "ArrowDown",
    });
    fireEvent.click(await screen.findByRole("menuitem", { name: "删除" }));
    expect(
      await screen.findByText(/将级联清理该文档的切片、向量与图谱贡献/),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
    expect(onDeleteDocument).toHaveBeenCalledWith("doc-1");
  });

  it("去操作标题列：尾部窄列无标题不占文案宽，无独立重试按钮，状态列不换行（2026-08-31）", () => {
    renderPanel({
      documents: [doc({ status: "failed", error: "boom", chunk_count: null })],
    });
    // 表格不再有「操作」标题列——删除收进尾部窄列的三个点与右键菜单兜底。
    expect(screen.queryByText("操作")).toBeNull();
    // 失败行也不为重试占宽；重试走窄列菜单/失败悬停卡/右键菜单。
    expect(screen.queryByRole("button", { name: "重试" })).toBeNull();
    // 状态单元格单行不换行（图 1 反馈：失败行被撑高换行）
    expect(screen.getByText("失败").closest("td")!.className).toContain(
      "whitespace-nowrap",
    );
  });

  it("悬停失败状态出卡片：友好原因 + 重试按钮（错误不常驻，重试不丢）", async () => {
    const handlers = renderPanel({
      documents: [
        doc({
          status: "failed",
          error: "retry limit reached (5 attempts)",
          chunk_count: null,
        }),
      ],
    });
    const trigger = screen.getByTestId("doc-retry-trigger");
    fireEvent.pointerEnter(trigger);
    fireEvent.pointerMove(trigger);
    const card = await screen.findByTestId("doc-retry-card");
    expect(card.textContent).toContain("解析服务多次重试仍失败");
    expect(card.textContent).not.toContain("retry limit");
    fireEvent.click(within(card).getByRole("button", { name: "重试" }));
    expect(handlers.onRetryDocument).toHaveBeenCalledWith("doc-1");
  });

  it("降级行悬停出重试卡：说明 + 重试按钮 + 明细行，说明不点名具体腿（D2=甲，2026-10-04）", async () => {
    const handlers = renderPanel({
      documents: [
        doc({
          path_status: {
            vector: "done",
            caption: "degraded",
          },
        }),
      ],
    });
    const trigger = screen.getByTestId("doc-retry-trigger");
    fireEvent.pointerEnter(trigger);
    fireEvent.pointerMove(trigger);
    const card = await screen.findByTestId("doc-retry-card");
    // 说明句只说「有产物未成功、可重试」，具体腿由卡内明细行自证——配文一词
    // 只允许出现在 breakdown 里，不出现在说明句里（spec §2.5）。
    const hint = card.querySelector("p")!;
    expect(hint.textContent).toContain("部分产物未成功");
    expect(hint.textContent).not.toContain("配文");
    expect(
      within(card).getByTestId("path-status-breakdown").textContent,
    ).toContain("配文");
    fireEvent.click(within(card).getByRole("button", { name: "重试" }));
    expect(handlers.onRetryDocument).toHaveBeenCalledWith("doc-1");
  });

  it("批量右键的取消选择带 X 图标且能清选择（2026-09-02）", () => {
    renderPanel({
      documents: [
        doc({ id: "doc-1" }),
        doc({ id: "doc-2", name: "并发笔记.md" }),
      ],
    });
    fireEvent.click(screen.getByLabelText("选择文档: 产品手册.pdf"));
    fireEvent.click(screen.getByLabelText("选择文档: 并发笔记.md"));
    fireEvent.contextMenu(screen.getByText("并发笔记.md"));
    const items = screen.getAllByRole("menuitem");
    const names = items.map((item) => item.textContent);
    // 切片裁掉出题面：批量菜单只剩取消选择 + 删除所选。
    expect(names).toEqual(["取消选择", "删除所选"]);
    const cancel = items[0]!;
    expect(cancel.querySelector("svg")).toBeTruthy();
    fireEvent.click(cancel);
    // 选择清空：两行复选框都回到未勾选（批量栏已退役，看行状态）。
    expect(screen.getByLabelText("选择文档: 产品手册.pdf").getAttribute("aria-checked")).toBe("false");
    expect(screen.getByLabelText("选择文档: 并发笔记.md").getAttribute("aria-checked")).toBe("false");
  });

  it("单选右键菜单也提供取消选择（两态对称，2026-09-02）", () => {
    renderPanel();
    fireEvent.click(screen.getByLabelText("选择文档: 产品手册.pdf"));
    fireEvent.contextMenu(screen.getByText("产品手册.pdf"));
    const cancel = screen.getByRole("menuitem", { name: "取消选择" });
    expect(cancel.querySelector("svg")).toBeTruthy();
    fireEvent.click(cancel);
    expect(screen.getByLabelText("选择文档: 产品手册.pdf").getAttribute("aria-checked")).toBe("false");
  });

  it("单选右键菜单删除项措辞对齐批量栏（删除所选，2026-09-02）", () => {
    renderPanel();
    fireEvent.contextMenu(screen.getByText("产品手册.pdf"));
    // 右键即选中，删除目标就是选择集——同屏措辞同一词汇；
    // 精确 name 匹配，「删除所选」不再命中旧文案「删除」。
    expect(screen.getByRole("menuitem", { name: "删除所选" })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: "删除" })).toBeNull();
  });
});

// ── 悬停三个点窄列（2026-08-31）────────────────────────────
// 定案（用户拍板）：切片数后预留一窄列承接三个点（Drive/SharePoint 惯例，
// 不遮数值）；菜单镜像右键菜单（查看切片/重试/删除）；右键菜单保留兜底。
describe("DocumentPanel 悬停三个点窄列", () => {
  it("三个点住在尾部预留窄列：默认隐藏、悬停淡入，不遮切片数/大小", () => {
    renderPanel();
    const pill = screen.getByTestId("doc-row-more");
    expect(pill.className).toContain("opacity-0");
    expect(pill.className).toContain("group-hover:opacity-100");
    // 预留列方案（非覆盖式）：不再需要绝对定位/模糊底纹，列本身就是位置。
    expect(pill.className).not.toContain("absolute");
    expect(pill.closest("td")!.className).toContain("w-10");
  });

  it("三个点菜单镜像右键菜单：查看切片 + 删除；就绪行无重试", async () => {
    renderPanel();
    fireEvent.keyDown(screen.getByRole("button", { name: "更多操作" }), {
      key: "ArrowDown",
    });
    expect(
      await screen.findByRole("menuitem", { name: /查看切片/ }),
    ).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: /删除/ })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: /重试/ })).toBeNull();
  });

  it("失败行窄列菜单额外提供重试", async () => {
    const handlers = renderPanel({
      documents: [doc({ status: "failed", error: "boom", chunk_count: null })],
    });
    fireEvent.keyDown(screen.getByRole("button", { name: "更多操作" }), {
      key: "ArrowDown",
    });
    fireEvent.click(await screen.findByRole("menuitem", { name: /重试/ }));
    expect(handlers.onRetryDocument).toHaveBeenCalledWith("doc-1");
  });

  it("降级行窄列菜单同步提供重试（两处入口一致，2026-10-04）", async () => {
    const handlers = renderPanel({
      documents: [
        doc({
          path_status: {
            vector: "done",
            caption: "degraded",
          },
        }),
      ],
    });
    fireEvent.keyDown(screen.getByRole("button", { name: "更多操作" }), {
      key: "ArrowDown",
    });
    fireEvent.click(await screen.findByRole("menuitem", { name: /重试/ }));
    expect(handlers.onRetryDocument).toHaveBeenCalledWith("doc-1");
  });

  it("菜单查看切片回流 onOpenChunks；点击三个点本身不触发行级打开", async () => {
    const handlers = renderPanel();
    // 窄列内的点击被单元格 stopPropagation，不会冒泡到行级 onClick
    fireEvent.click(screen.getByRole("button", { name: "更多操作" }));
    expect(handlers.onOpenChunks).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole("button", { name: "更多操作" }), {
      key: "ArrowDown",
    });
    fireEvent.click(await screen.findByRole("menuitem", { name: /查看切片/ }));
    expect(handlers.onOpenChunks).toHaveBeenCalledTimes(1);
  });
});

// ── 大小统一 KB 与批量栏图标（2026-08-31）──────────────────
// 定案（用户拍板）：表头不带单位，每个单元格自带 KB 后缀、纯数字千分位，
// <1KB 向上取整为 1（Windows 惯例），精确字节收进悬停 Tooltip。
describe("DocumentPanel 大小 KB 统一与批量栏", () => {
  it("大小单元格带 KB 后缀：千分位、<1KB 取整为 1", () => {
    renderPanel({
      documents: [
        doc({ id: "a", name: "大文件.pdf", size_bytes: 5 * 1024 * 1024 }),
        doc({ id: "b", name: "小文件.txt", size_bytes: 300 }),
      ],
    });
    const sizeValue = (name: string) =>
      within(screen.getByText(name).closest("tr")!).getByTestId(
        "doc-size-value",
      ).textContent;
    expect(sizeValue("大文件.pdf")).toBe("5,120 KB");
    expect(sizeValue("小文件.txt")).toBe("1 KB");
  });

  it("悬停大小出精确字节 Tooltip（不占列宽又保留精确信息）", async () => {
    renderPanel(); // 默认 doc 2048 bytes
    const value = screen.getByTestId("doc-size-value");
    fireEvent.pointerEnter(value);
    fireEvent.pointerMove(value);
    expect((await screen.findByRole("tooltip")).textContent).toContain(
      "2,048 B",
    );
  });

  it("批量栏退役：选中后工具栏不再切换，搜索/排序常驻（2026-09-02）", () => {
    renderPanel();
    fireEvent.click(screen.getByLabelText("选择文档: 产品手册.pdf"));
    expect(screen.queryByTestId("document-batch-bar")).toBeNull();
    expect(screen.getByLabelText("搜索文档…")).toBeTruthy();
    expect(screen.getByRole("button", { name: "排序方式" })).toBeTruthy();
  });
});

describe("DocumentPanel stats row and upload", () => {
  it("aggregates the bottom stats row client-side", () => {
    renderPanel({
      documents: [
        doc({ id: "a", status: "ready", size_bytes: 1024, chunk_count: 5 }),
        doc({
          id: "b",
          status: "indexing",
          size_bytes: 1024,
          chunk_count: null,
        }),
        doc({ id: "c", status: "failed", size_bytes: 2048, chunk_count: null }),
      ],
    });
    const statsRow = screen.getByTestId("document-stats-row");
    expect(statsRow.textContent).toContain("3");
    expect(statsRow.textContent).toContain("4.0 KB");
    expect(statsRow.textContent).toContain("5");
  });

  it("splits the stats row into volume + status segments, hiding zero counts", () => {
    // Spec 2026-09-24 settings-responsive-layout §7.2 甲: two nowrap segments (volume left,
    // status right) wrap as wholes, and a zero count stays silent instead of shouting "0".
    renderPanel({
      documents: [
        doc({ id: "a", status: "ready", size_bytes: 1024, chunk_count: 5 }),
        doc({ id: "b", status: "failed", size_bytes: 2048, chunk_count: null }),
      ],
    });
    const row = screen.getByTestId("document-stats-row");

    const statusSegment = row.lastElementChild as HTMLElement;
    expect(statusSegment.className).toContain("ml-auto");

    // Zero counts stay silent; non-zero ones show with the status column's own dots.
    expect(row.textContent).not.toContain("索引中");
    expect(row.textContent).toContain("就绪");
    expect(row.textContent).toContain("失败");
    expect(statusSegment.querySelector(".bg-emerald-500\\/45")).toBeTruthy();
    expect(statusSegment.querySelector(".bg-destructive")).toBeTruthy();
  });

  it("uploads via drag-drop on the panel", () => {
    const { onUpload } = renderPanel();
    const zone = screen.getByTestId("document-dropzone");
    const file = new File(["x"], "拖入.md", { type: "text/markdown" });
    fireEvent.drop(zone, { dataTransfer: { files: [file] } });
    expect(onUpload).toHaveBeenCalledWith([file]);
  });

  it("intercepts unsupported dropped files before upload (Task 6)", () => {
    const { onUpload } = renderPanel();
    const zone = screen.getByTestId("document-dropzone");
    const good = new File(["y"], "拖入.txt");
    fireEvent.drop(zone, {
      dataTransfer: { files: [new File(["x"], "evil.exe"), good] },
    });
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringContaining("evil.exe"),
      expect.objectContaining({ toasterId: KB_TOASTER_ID }),
    );
    expect(onUpload).toHaveBeenCalledTimes(1);
    expect(onUpload).toHaveBeenCalledWith([good]);
  });

  it("shows a drop-hint overlay while a file is dragged over the panel", () => {
    renderPanel();
    const zone = screen.getByTestId("document-dropzone");
    expect(screen.queryByTestId("document-drop-overlay")).toBeNull();
    fireEvent.dragOver(zone);
    expect(screen.getByTestId("document-drop-overlay")).toBeTruthy();
    expect(screen.getByText("释放以上传到当前知识库")).toBeTruthy();
    fireEvent.dragLeave(zone);
    expect(screen.queryByTestId("document-drop-overlay")).toBeNull();
  });

  it("shows the empty-state copy when the kb has no documents", () => {
    renderPanel({ documents: [] });
    expect(screen.getByText(/上传或拖拽文件开始构建索引/)).toBeTruthy();
  });
});

describe("DocumentPanel per-path status hover (P3, spec 2026-08-11 §5)", () => {
  it("wraps the status badge with a tooltip trigger when path_status is present", () => {
    renderPanel({
      documents: [
        doc({
          status: "indexing",
          progress_percent: 87,
          chunk_count: null,
          path_status: { vector: "indexing" },
        }),
      ],
    });
    expect(screen.getByTestId("path-status-trigger")).toBeTruthy();
  });

  it("renders no tooltip trigger for legacy rows whose path_status is null", () => {
    renderPanel();
    expect(screen.queryByTestId("path-status-trigger")).toBeNull();
  });

  it("assembles the two-leg breakdown (vector + caption)", () => {
    render(
      <I18nContext.Provider
        value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}
      >
        <PathStatusBreakdown
          doc={doc({
            status: "indexing",
            progress_percent: 87,
            path_status: { vector: "indexing", caption: "done" },
          })}
        />
      </I18nContext.Provider>,
    );
    const breakdown = screen.getByTestId("path-status-breakdown");
    expect(breakdown.textContent).toContain("向量");
    expect(breakdown.textContent).toContain("索引中");
    expect(breakdown.textContent).toContain("配文");
    expect(breakdown.textContent).toContain("已完成");
    // 切片不组合百分比：progress_percent 只喂进度条，不进悬停明细。
    expect(breakdown.textContent).not.toContain("%");
  });

  it("renders degraded / failed states verbatim", () => {
    render(
      <I18nContext.Provider
        value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}
      >
        <PathStatusBreakdown
          doc={doc({
            status: "ready",
            path_status: { vector: "failed", caption: "degraded" },
          })}
        />
      </I18nContext.Provider>,
    );
    const breakdown = screen.getByTestId("path-status-breakdown");
    expect(breakdown.textContent).toContain("失败");
    expect(breakdown.textContent).toContain("部分降级");
    // degraded 着琥珀（对齐项目 caution 视觉词汇）。
    expect(
      breakdown.querySelector('[data-state="degraded"]')!.className,
    ).toContain("text-amber-600");
    // 就绪态不组合百分比
    expect(breakdown.textContent).not.toContain("%");
  });

  it("pathStatusLines returns null for legacy rows (no hover)", () => {
    expect(pathStatusLines(doc({ path_status: null }))).toBeNull();
  });
});

describe("DocumentPanel toolbar", () => {
  const docs = [
    doc({
      id: "a",
      name: "产品手册.pdf",
      size_bytes: 4096,
      created_at: "2026-08-08T10:00:00Z",
    }),
    doc({
      id: "b",
      name: "Roadmap.md",
      size_bytes: 1024,
      created_at: "2026-08-09T09:00:00Z",
    }),
    doc({
      id: "c",
      name: "研发规范.docx",
      size_bytes: 2048,
      created_at: "2026-08-09T10:00:00Z",
    }),
  ];

  function rowNames(): string[] {
    // First column is the selection checkbox; the name is the second cell.
    // 只取文件名 span：类型徽章是 aria-hidden 的 SVG，其字形（W/M）不进名称。
    return [...document.querySelectorAll("tbody tr td:nth-child(2)")].map(
      (cell) => cell.querySelector("span.truncate")?.textContent ?? "",
    );
  }

  it("filters rows by the search box and offers a clear button", () => {
    renderPanel({ documents: docs });
    const search = screen.getByPlaceholderText("搜索文档…");
    fireEvent.change(search, { target: { value: "roadmap" } });
    expect(rowNames()).toEqual(["Roadmap.md"]);
    fireEvent.click(screen.getByRole("button", { name: "清空搜索" }));
    expect(rowNames()).toHaveLength(3);
  });

  it("shows the no-match hint when the filter matches nothing", () => {
    renderPanel({ documents: docs });
    fireEvent.change(screen.getByPlaceholderText("搜索文档…"), {
      target: { value: "不存在" },
    });
    expect(screen.getByText("没有匹配的文档")).toBeTruthy();
  });

  it("sorts by upload time descending by default and re-sorts via the dropdown", async () => {
    renderPanel({ documents: docs });
    expect(rowNames()).toEqual(["研发规范.docx", "Roadmap.md", "产品手册.pdf"]);

    fireEvent.keyDown(screen.getByRole("button", { name: "排序方式" }), {
      key: "ArrowDown",
    });
    fireEvent.click(await screen.findByRole("menuitem", { name: "大小" }));
    expect(rowNames()).toEqual(["产品手册.pdf", "研发规范.docx", "Roadmap.md"]);

    fireEvent.keyDown(screen.getByRole("button", { name: "排序方式" }), {
      key: "ArrowDown",
    });
    fireEvent.click(await screen.findByRole("menuitem", { name: "升序" }));
    expect(rowNames()).toEqual(["Roadmap.md", "研发规范.docx", "产品手册.pdf"]);
  });
});

// ── 状态与文件类型徽章视觉 ─────────────────────────
// 定案：文件名是第一扫描目标——状态改圆点+小字（Linear 风格，就绪退后、
// 失败唯一抢眼）；文件图标用设计稿导出的 56 网格几何（2026-08-31 定稿）。
describe("DocumentPanel 状态与类型图标", () => {
  function rowOf(name: string) {
    return screen.getByText(name).closest("tr")!;
  }

  it("就绪态：降饱和绿点悬挂在文字外 + muted 小字（视觉降级）", () => {
    renderPanel({ documents: [doc({ name: "手册.pdf" })] });
    const row = rowOf("手册.pdf");
    const dot = row.querySelector("span.rounded-full")!;
    // /45 而非全饱和：常态退后，让失败成为行内唯一的饱和色
    expect(dot.className).toContain("bg-emerald-500/45");
    // 绝对定位挂在文字外，文字左缘才是对齐表头的那条边
    expect(dot.className).toContain("absolute");
    // 文本退为次要色，且不在 Badge 组件内（data-slot=badge）
    const statusLabel = Array.from(row.querySelectorAll("span")).find(
      (span) => span.textContent === "就绪" && span.childElementCount === 0,
    )!;
    expect(statusLabel.className).toContain("text-muted-foreground");
    expect(statusLabel.closest("[data-slot='badge']")).toBeNull();
  });

  it("进行中：琥珀圆点；失败：红点+红字（唯一突出的异常态）", () => {
    renderPanel({
      documents: [
        doc({
          id: "d-idx",
          name: "索引中.pdf",
          status: "indexing",
          progress_percent: 40,
        }),
        doc({
          id: "d-fail",
          name: "失败.pdf",
          status: "failed",
          error: "解析出错",
        }),
      ],
    });
    expect(rowOf("索引中.pdf").querySelector("span.bg-amber-500")).toBeTruthy();
    const failedRow = rowOf("失败.pdf");
    expect(failedRow.querySelector("span.bg-destructive")).toBeTruthy();
    const failedLabel = Array.from(failedRow.querySelectorAll("span")).find(
      (span) => span.textContent === "失败" && span.childElementCount === 0,
    )!;
    expect(failedLabel.className).toContain("text-destructive");
  });

  it("文件图标为设计稿 56 网格图标：形状定类型、颜色定族，未知后缀灰色兜底（2026-08-31 定稿）", () => {
    renderPanel({
      documents: [
        doc({ id: "d1", name: "手册.pdf" }),
        doc({ id: "d2", name: "笔记.md" }),
        doc({ id: "d3", name: "截图.jpg" }),
        doc({ id: "d4", name: "数据.csv" }),
        doc({ id: "d5", name: "规范.docx" }),
        doc({ id: "d6", name: "演示.pptx" }),
        doc({ id: "d7", name: "未知.xyz" }),
      ],
    });
    // 图标几何直接内联自 Ardot 主组件，viewBox 仍是 56 网格；行内取 20px，
    // 再往下 3.5px 的细节条会压成 1px 发丝、折角糊掉。
    const badgeOf = (name: string) =>
      rowOf(name).querySelector("svg[data-filetype]")!;
    expect(badgeOf("手册.pdf").getAttribute("viewBox")).toBe("0 0 56 56");
    expect(badgeOf("手册.pdf").getAttribute("class")).toContain("size-5");
    // 纸面族第一块着色 = 设计稿主色
    const sheetFillOf = (name: string) =>
      badgeOf(name).querySelector("path")!.getAttribute("fill");
    expect(sheetFillOf("手册.pdf")).toBe("#DC2626");
    expect(sheetFillOf("规范.docx")).toBe("#2563EB");
    expect(sheetFillOf("演示.pptx")).toBe("#F97316");
    expect(sheetFillOf("数据.csv")).toBe("#16A34A");
    // 决策①：Markdown 并入「代码与数据」青色，不再与 .docx 同为文档蓝
    expect(sheetFillOf("笔记.md")).toBe("#0891B2");
    // 图片是圆角屏体而非纸面，着色落在 rect 上
    expect(
      badgeOf("截图.jpg").querySelector("rect")!.getAttribute("fill"),
    ).toBe("#8B5CF6");
    // 未知后缀：只剩折角页轮廓的灰色兜底，不假装有类型信息
    expect(badgeOf("未知.xyz").getAttribute("data-filetype")).toBe("unknown");
    expect(sheetFillOf("未知.xyz")).toBe("#64748B");
    // 区分不依赖读文件名，图标内不渲染任何文字
    expect(badgeOf("手册.pdf").textContent).toBe("");
  });
});

// ── 失败通知面板接线（2026-08-31）────────────────────────────
// 定案（用户拍板）：错误通知退出全局 sonner toast（视口级，出 tab），
// 改为文档 tab 内右下角自绘面板；✕ 右侧、折叠/展开、总关/单关、不自动消失。
describe("DocumentPanel 失败通知面板接线", () => {
  it("有失败条目时渲染面板：文件名/原因两行，绝对定位在 tab 内右下角", () => {
    renderPanel({
      failures: [
        {
          key: "doc-1",
          name: "户号.pptx",
          reason: "文件内容为空",
          retryable: true,
        },
      ],
      onDismissFailure: rs.fn(),
      onDismissAllFailures: rs.fn(),
    });
    const panel = screen.getByTestId("doc-failure-panel");
    expect(panel.className).toContain("absolute");
    expect(panel.className).toContain("bottom-3");
    expect(screen.getByText("户号.pptx")).toBeTruthy();
    expect(screen.getByText("文件内容为空")).toBeTruthy();
  });

  it("无失败条目时不渲染面板（默认 props 即可）", () => {
    renderPanel();
    expect(screen.queryByTestId("doc-failure-panel")).toBeNull();
  });

  it("面板关闭动作回流到页面层回调", () => {
    const onDismissFailure = rs.fn();
    const onDismissAllFailures = rs.fn();
    renderPanel({
      failures: [
        {
          key: "doc-1",
          name: "户号.pptx",
          reason: "文件内容为空",
          retryable: true,
        },
      ],
      onDismissFailure,
      onDismissAllFailures,
    });
    fireEvent.click(screen.getByRole("button", { name: "全部关闭" }));
    expect(onDismissAllFailures).toHaveBeenCalledTimes(1);
    expect(onDismissFailure).not.toHaveBeenCalled();
  });

  it("面板内重试回流到 onRetryDocument（条目 key 即文档 id）", () => {
    const handlers = renderPanel({
      failures: [
        {
          key: "doc-1",
          name: "户号.pptx",
          reason: "文件内容为空",
          retryable: true,
        },
      ],
      onDismissFailure: rs.fn(),
      onDismissAllFailures: rs.fn(),
    });
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(handlers.onRetryDocument).toHaveBeenCalledWith("doc-1");
  });
});

// ── 逐腿状态（首期：vector + caption）────────────────────────────────────
describe("PathStatusBreakdown 首期两腿 + degraded 琥珀", () => {
  it("pathStatusLines 带 caption 键时多出配文一行（排在 vector 之前）", () => {
    const lines = pathStatusLines(
      doc({
        path_status: {
          caption: "degraded",
          vector: "done",
        },
      }),
    );
    expect(lines!.map((line) => line.path)).toEqual(["caption", "vector"]);
    expect(lines!.find((line) => line.path === "caption")!.state).toBe("degraded");
  });

  it("pathStatusLines 不带 caption 键时只有 vector 一行", () => {
    const lines = pathStatusLines(doc({ path_status: { vector: "done" } }));
    expect(lines!.map((line) => line.path)).toEqual(["vector"]);
  });

  it("caption 为 null（未走到该腿）时不渲染配文行", () => {
    const lines = pathStatusLines(
      doc({ path_status: { vector: "pending", caption: null } }),
    );
    expect(lines!.map((line) => line.path)).toEqual(["vector"]);
  });

  it("degraded 腿的状态文案着琥珀色，done 腿不着色", () => {
    render(
      <I18nContext.Provider
        value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}
      >
        <PathStatusBreakdown
          doc={doc({
            status: "ready",
            path_status: {
              caption: "degraded",
              vector: "done",
            },
          })}
        />
      </I18nContext.Provider>,
    );
    const breakdown = screen.getByTestId("path-status-breakdown");
    const captionState = breakdown.querySelector(
      "[data-path='caption'] [data-state='degraded']",
    );
    expect(captionState?.className).toContain("text-amber-600");
    const vectorState = breakdown.querySelector(
      "[data-path='vector'] [data-state='done']",
    );
    expect(vectorState?.className).not.toContain("text-amber");
  });
});
