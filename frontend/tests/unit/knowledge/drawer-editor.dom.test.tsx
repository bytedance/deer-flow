/**
 * 抽屉创建/编辑弹窗（2026-09-04）：Qoder 式精简——名称 + 图标网格(12) + 颜色网格(12)，
 * 无描述文案；名称非空才可提交；提交回调带 (name, icon, color)；编辑态预填 initial。
 */
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { DrawerEditor } from "@/components/workspace/knowledge/drawer-editor";
import { I18nContext } from "@/core/i18n/context";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import {
  DRAWER_COLOR_KEYS,
  DRAWER_ICON_KEYS,
  type CardDrawer,
  type DrawerColorKey,
  type DrawerIconKey,
} from "@/core/knowledge/card-drawers";

function renderEditor(props?: {
  initial?: CardDrawer | null;
  onSubmit?: (name: string, icon: DrawerIconKey, color: DrawerColorKey) => void;
}) {
  const onSubmit = props?.onSubmit ?? rs.fn();
  render(
    <I18nContext.Provider
      value={{ locale: "zh-CN", setLocale: () => undefined, t: zhCN }}
    >
      <DrawerEditor
        initial={props?.initial ?? null}
        open={true}
        onOpenChange={() => undefined}
        onSubmit={onSubmit}
      />
    </I18nContext.Provider>,
  );
  return { onSubmit };
}

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("DrawerEditor", () => {
  it("名称为空时提交禁用，输入后启用", () => {
    renderEditor();
    const submit = screen.getByRole("button", { name: "创建" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("名称"), {
      target: { value: "运维手册" },
    });
    expect((submit as HTMLButtonElement).disabled).toBe(false);
  });

  it("渲染 12 个图标 + 12 个颜色单元（单行、数量一致、列对齐）", () => {
    renderEditor();
    expect(DRAWER_ICON_KEYS).toHaveLength(12);
    expect(DRAWER_COLOR_KEYS).toHaveLength(12);
    for (const key of DRAWER_ICON_KEYS) {
      expect(screen.getByTestId(`drawer-icon-${key}`)).toBeTruthy();
    }
    for (const key of DRAWER_COLOR_KEYS) {
      expect(screen.getByTestId(`drawer-color-${key}`)).toBeTruthy();
    }
  });

  it("默认 icon=folder / color=emerald，提交回调带 trim 后的 (name, icon, color)", () => {
    const onSubmit = rs.fn();
    renderEditor({ onSubmit });
    fireEvent.change(screen.getByTestId("drawer-editor-name"), {
      target: { value: "  产品  " },
    });
    expect(
      screen.getByTestId("drawer-icon-folder").getAttribute("aria-pressed"),
    ).toBe("true");
    expect(
      screen.getByTestId("drawer-color-emerald").getAttribute("aria-pressed"),
    ).toBe("true");
    fireEvent.click(screen.getByTestId("drawer-editor-submit"));
    expect(onSubmit).toHaveBeenCalledWith("产品", "folder", "emerald");
  });

  it("选图标 / 选色更新 aria-pressed 高亮与提交值", () => {
    const onSubmit = rs.fn();
    renderEditor({ onSubmit });
    fireEvent.change(screen.getByTestId("drawer-editor-name"), {
      target: { value: "x" },
    });
    fireEvent.click(screen.getByTestId("drawer-icon-star"));
    fireEvent.click(screen.getByTestId("drawer-color-rose"));
    expect(
      screen.getByTestId("drawer-icon-star").getAttribute("aria-pressed"),
    ).toBe("true");
    expect(
      screen.getByTestId("drawer-icon-folder").getAttribute("aria-pressed"),
    ).toBe("false");
    expect(
      screen.getByTestId("drawer-color-rose").getAttribute("aria-pressed"),
    ).toBe("true");
    fireEvent.click(screen.getByTestId("drawer-editor-submit"));
    expect(onSubmit).toHaveBeenCalledWith("x", "star", "rose");
  });

  it("编辑态预填 initial（名称/图标/色）并用「编辑抽屉」标题", () => {
    renderEditor({
      initial: { id: "d1", name: "运维手册", icon: "flag", color: "blue" },
    });
    const nameField = screen.getByRole("textbox", { name: "名称" });
    expect((nameField as HTMLInputElement).value).toBe("运维手册");
    expect(
      screen.getByTestId("drawer-icon-flag").getAttribute("aria-pressed"),
    ).toBe("true");
    expect(
      screen.getByTestId("drawer-color-blue").getAttribute("aria-pressed"),
    ).toBe("true");
    expect(screen.getByText("编辑抽屉")).toBeTruthy();
  });
});
