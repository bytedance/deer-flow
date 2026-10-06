/**
 * 文档表格列显隐与格式切换（2026-09-02，方案 Task 4）：可隐藏列的条件渲染 +
 * 时间格式（绝对/相对）+ 大小单位（KB/MB）应用。本文件只验证「偏好驱动渲染」——
 * 通过预置 localStorage 偏好控制，UI 菜单入口在 Task 5/6（另有交互测试）。
 * harness 精简自 document-panel.dom.test.tsx。
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { DocumentPanel } from "@/components/workspace/knowledge/document-panel";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import type { KnowledgeBase, KnowledgeDocument } from "@/core/knowledge/types";
import {
  writeDocTablePrefs,
  type DocTablePrefs,
} from "@/core/knowledge/use-doc-table-prefs";

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

const DAY_MS = 24 * 60 * 60 * 1000;

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

/** 预置该库偏好（缺省字段回退默认），再挂载面板。 */
function renderPanel(
  prefs?: Partial<DocTablePrefs>,
  docs: KnowledgeDocument[] = [doc({})],
) {
  if (prefs) {
    writeDocTablePrefs(KB.id, {
      hidden: [],
      timeFormat: "absolute",
      sizeUnit: "kb",
      ...prefs,
    });
  }
  render(
    <I18nContext.Provider
      value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}
    >
      <DocumentPanel
        kb={KB}
        documents={docs}
        supportedSuffixes={[".md", ".pdf", ".txt"]}
        onUpload={rs.fn()}
        onDeleteDocument={rs.fn().mockResolvedValue(undefined)}
        onRetryDocument={rs.fn()}
        onOpenChunks={rs.fn()}
      />
    </I18nContext.Provider>,
  );
}

function headerLabels(): (string | undefined)[] {
  return Array.from(screen.getAllByRole("columnheader")).map((h) =>
    h.textContent?.trim(),
  );
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("列显隐：偏好驱动条件渲染", () => {
  it("默认全显：名称|状态|上传者|时间|大小|切片数（+ 复选框/尾列）", () => {
    renderPanel();
    expect(headerLabels()).toEqual([
      "",
      "名称",
      "状态",
      "上传者",
      "时间",
      "大小",
      "切片数",
      "",
    ]);
  });

  it("隐藏上传者列：th 与 td 一起消失，其余列保持", () => {
    renderPanel({ hidden: ["uploader"] });
    expect(screen.queryByText("上传者")).toBeNull();
    // 上传者内容（uploaderMe="我"）也随之消失。
    expect(screen.queryByText("我")).toBeNull();
    expect(headerLabels()).toEqual([
      "",
      "名称",
      "状态",
      "时间",
      "大小",
      "切片数",
      "",
    ]);
  });

  it("隐藏多个数值列：时间/大小/切片数同时消失，名称/状态/上传者仍在", () => {
    renderPanel({ hidden: ["createdAt", "size", "chunks"] });
    expect(screen.queryByText("时间")).toBeNull();
    expect(screen.queryByText("大小")).toBeNull();
    expect(screen.queryByText("切片数")).toBeNull();
    expect(screen.queryByTestId("doc-size-value")).toBeNull();
    expect(headerLabels()).toEqual(["", "名称", "状态", "上传者", ""]);
  });

  it("名称不可隐藏：即使偏好里塞入也被类型守卫滤掉，列仍在", () => {
    // writeDocTablePrefs 直接写入（绕过 hook 的 sanitize），验证渲染层也不塌。
    window.localStorage.setItem(
      `deerflow.knowledge.doc-table-prefs.${KB.id}.v1`,
      JSON.stringify({
        hidden: ["name"],
        timeFormat: "absolute",
        sizeUnit: "kb",
      }),
    );
    renderPanel();
    expect(screen.getByText("名称")).toBeTruthy();
  });

  // 状态列自 2026-09-03 接入同一套隐藏逻辑（原本与名称一同钉死）。
  // 本用例同时守住类型守卫：偏好经 writeDocTablePrefs → readDocTablePrefs
  // 往返，若 status 仍被过滤则列不会隐，测试即红。
  it("隐藏状态列：th 与状态单元格一起消失，其余列保持", () => {
    renderPanel({ hidden: ["status"] });
    expect(screen.queryByText("状态")).toBeNull();
    expect(headerLabels()).toEqual([
      "",
      "名称",
      "上传者",
      "时间",
      "大小",
      "切片数",
      "",
    ]);
    // td 与 th 同步收缩（否则表头与数据错列）：8 列 → 7 列。
    expect(screen.getAllByRole("cell")).toHaveLength(7);
  });
});

describe("时间格式切换：偏好驱动", () => {
  it("默认绝对：显示 2026/08/09", () => {
    renderPanel();
    expect(screen.getByText(/2026\/08\/09/)).toBeTruthy();
  });

  it("相对：显示「N 天前」而非绝对日期", () => {
    const threeDaysAgo = new Date(Date.now() - 3 * DAY_MS).toISOString();
    renderPanel({ timeFormat: "relative" }, [
      doc({ created_at: threeDaysAgo }),
    ]);
    // 相对时间不含绝对年份，含「天前」（zh numeric:auto，3 天）。
    expect(screen.queryByText(/2026\/\d{2}\/\d{2}/)).toBeNull();
    expect(screen.getByText(/天前/)).toBeTruthy();
  });
});

describe("大小单位切换：偏好驱动", () => {
  it("默认 KB：2 KB（2048 bytes）", () => {
    renderPanel();
    const size = screen.getByTestId("doc-size-value").textContent ?? "";
    expect(size).toContain("2");
    expect(size).toContain("KB");
  });

  it("MB：5.0 MB（5 MiB）", () => {
    renderPanel({ sizeUnit: "mb" }, [doc({ size_bytes: 5 * 1024 * 1024 })]);
    const size = screen.getByTestId("doc-size-value").textContent ?? "";
    expect(size).toContain("5.0");
    expect(size).toContain("MB");
  });
});

describe("单列表头 chevron 菜单（Task 5）", () => {
  it("chevron 打开菜单 → 点隐藏列 → 该列 th/td 消失", () => {
    renderPanel();
    // Radix DropdownMenu 在 jsdom 用 keyDown(ArrowDown) 打开（不响应 click）。
    fireEvent.keyDown(screen.getByRole("button", { name: "上传者 列选项" }), {
      key: "ArrowDown",
    });
    fireEvent.click(screen.getByRole("menuitem", { name: "隐藏列" }));
    expect(screen.queryByText("上传者")).toBeNull();
    expect(screen.queryByText("我")).toBeNull();
  });

  it("状态列菜单：只有隐藏列（无格式/单位可切）", () => {
    renderPanel();
    fireEvent.keyDown(screen.getByRole("button", { name: "状态 列选项" }), {
      key: "ArrowDown",
    });
    const items = screen.getAllByRole("menuitem");
    expect(items.map((item) => item.textContent)).toEqual(["隐藏列"]);
    fireEvent.click(items[0]!);
    expect(screen.queryByText("状态")).toBeNull();
    expect(screen.getAllByRole("cell")).toHaveLength(7);
  });

  it("时间列菜单：切换到相对格式", () => {
    const threeDaysAgo = new Date(Date.now() - 3 * DAY_MS).toISOString();
    renderPanel({}, [doc({ created_at: threeDaysAgo })]);
    fireEvent.keyDown(screen.getByRole("button", { name: "时间 列选项" }), {
      key: "ArrowDown",
    });
    fireEvent.click(screen.getByRole("menuitem", { name: "相对" }));
    expect(screen.getByText(/天前/)).toBeTruthy();
  });

  it("大小列菜单：切换单位到 MB", () => {
    renderPanel({}, [doc({ size_bytes: 5 * 1024 * 1024 })]);
    fireEvent.keyDown(screen.getByRole("button", { name: "大小 列选项" }), {
      key: "ArrowDown",
    });
    fireEvent.click(screen.getByRole("menuitem", { name: "MB" }));
    expect(screen.getByTestId("doc-size-value").textContent).toContain("MB");
  });
});

describe("表头末尾 Columns 总控（Task 6）", () => {
  it("末尾「列」按钮打开总控，列出可隐藏列 + 全部显示", () => {
    renderPanel();
    fireEvent.keyDown(screen.getByRole("button", { name: "列" }), {
      key: "ArrowDown",
    });
    expect(screen.getByRole("menuitem", { name: "状态" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "上传者" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "时间" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "大小" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "切片数" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "全部显示" })).toBeTruthy();
  });

  it("「列」按钮 hover 范围覆盖整行表头（group/colhead 挂在 tr 上，2026-09-02）", () => {
    renderPanel();
    const columnsButton = screen.getByRole("button", { name: "列" });
    // 淡入门控仍用 group-hover/colhead；但 group/colhead 已上移到表头 tr，
    // 故悬停任意表头格（名称/状态/上传者…）都触发，不再局限末尾窄列。
    expect(columnsButton.className).toContain("group-hover/colhead:opacity-100");
    const headerRow = columnsButton.closest("tr")!;
    expect(headerRow.className).toContain("group/colhead");
  });

  it("点列项切换显隐：隐藏上传者列", () => {
    renderPanel();
    fireEvent.keyDown(screen.getByRole("button", { name: "列" }), {
      key: "ArrowDown",
    });
    fireEvent.click(screen.getByRole("menuitem", { name: "上传者" }));
    expect(screen.queryByText("上传者")).toBeNull();
    expect(screen.queryByText("我")).toBeNull();
  });

  it("全部显示：恢复所有隐藏列", () => {
    renderPanel({ hidden: ["uploader", "size"] });
    expect(screen.queryByText("上传者")).toBeNull();
    expect(screen.queryByText("大小")).toBeNull();
    fireEvent.keyDown(screen.getByRole("button", { name: "列" }), {
      key: "ArrowDown",
    });
    fireEvent.click(screen.getByRole("menuitem", { name: "全部显示" }));
    expect(screen.getByText("上传者")).toBeTruthy();
    expect(screen.getByText("大小")).toBeTruthy();
  });
});

describe("表头右键菜单兜底（Task 7）", () => {
  it("右键表头弹出列总控菜单（与末尾按钮同内容）", () => {
    renderPanel();
    const headerRow = screen.getAllByRole("columnheader")[0]!.closest("tr")!;
    fireEvent.contextMenu(headerRow);
    expect(screen.getByRole("menuitem", { name: "状态" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "上传者" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "切片数" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "全部显示" })).toBeTruthy();
  });

  it("右键表头菜单可切换列显隐：隐藏切片数列", () => {
    renderPanel();
    const headerRow = screen.getAllByRole("columnheader")[0]!.closest("tr")!;
    fireEvent.contextMenu(headerRow);
    fireEvent.click(screen.getByRole("menuitem", { name: "切片数" }));
    expect(screen.queryByText("切片数")).toBeNull();
  });
});
