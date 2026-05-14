import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-hook-form", async () => {
  const actual = await vi.importActual("react-hook-form");
  return actual;
});

async function importFormBlock() {
  const mod = await import("@/components/genui/FormBlock");
  return mod.default;
}

describe("FormBlock multi-select rendering", () => {
  it("renders multi-select field with options", async () => {
    const FormBlock = await importFormBlock();
    const html = renderToStaticMarkup(
      React.createElement(FormBlock, {
        block: {
          props: {
            title: "选择设备",
            fields: [
              {
                name: "equipment_ids",
                type: "multi-select" as const,
                label: "设备列表",
                searchable: true,
                max_visible: 10,
                options: [
                  { label: "SE-001", value: "SE-001", group: "A区", description: "换热器-001" },
                  { label: "SE-002", value: "SE-002", group: "A区", description: "冷却器-002" },
                  { label: "SE-003", value: "SE-003", group: "B区", description: "塔器-003" },
                ],
              },
            ],
            default_values: { equipment_ids: ["SE-001", "SE-002", "SE-003"] },
            submit_label: "下一步",
          },
          callback_id: "daily-report-equipment",
        },
      }),
    );
    expect(html).toContain("设备列表");
    expect(html).toContain("SE-001");
    expect(html).toContain("SE-002");
    expect(html).toContain("SE-003");
    expect(html).toContain("换热器-001");
    expect(html).toContain("A区");
    expect(html).toContain("B区");
    expect(html).toContain("搜索");
    expect(html).toContain("全选");
  });

  it("renders search input when searchable is true", async () => {
    const FormBlock = await importFormBlock();
    const html = renderToStaticMarkup(
      React.createElement(FormBlock, {
        block: {
          props: {
            fields: [
              {
                name: "ids",
                type: "multi-select" as const,
                label: "Select",
                searchable: true,
                options: [{ label: "A", value: "a" }],
              },
            ],
            default_values: { ids: [] },
          },
        },
      }),
    );
    expect(html).toContain("搜索");
  });

  it("shows empty state when no options", async () => {
    const FormBlock = await importFormBlock();
    const html = renderToStaticMarkup(
      React.createElement(FormBlock, {
        block: {
          props: {
            fields: [
              {
                name: "ids",
                type: "multi-select" as const,
                label: "设备",
                options: [],
              },
            ],
            default_values: { ids: [] },
          },
        },
      }),
    );
    expect(html).toContain("无数据");
  });

  it("shows selected count", async () => {
    const FormBlock = await importFormBlock();
    const html = renderToStaticMarkup(
      React.createElement(FormBlock, {
        block: {
          props: {
            fields: [
              {
                name: "ids",
                type: "multi-select" as const,
                label: "设备",
                options: [
                  { label: "A", value: "a" },
                  { label: "B", value: "b" },
                ],
              },
            ],
            default_values: { ids: ["a"] },
          },
        },
      }),
    );
    expect(html).toContain("已选");
    expect(html).toContain("/ 2");
  });

  it("does not break existing select field", async () => {
    const FormBlock = await importFormBlock();
    const html = renderToStaticMarkup(
      React.createElement(FormBlock, {
        block: {
          props: {
            fields: [
              {
                name: "type",
                type: "select" as const,
                label: "类型",
                options: [
                  { label: "全部", value: "all" },
                  { label: "静设备", value: "static" },
                ],
              },
            ],
            default_values: { type: "all" },
          },
        },
      }),
    );
    expect(html).toContain("类型");
    expect(html).toContain("全部");
    expect(html).toContain("静设备");
    expect(html).not.toContain("搜索");
    expect(html).not.toContain("全选");
  });

  it("does not break existing text field", async () => {
    const FormBlock = await importFormBlock();
    const html = renderToStaticMarkup(
      React.createElement(FormBlock, {
        block: {
          props: {
            fields: [
              { name: "name", type: "text" as const, label: "名称", placeholder: "输入..." },
            ],
          },
        },
      }),
    );
    expect(html).toContain("名称");
    expect(html).toContain("输入...");
  });

  it("renders group headers with collapse controls", async () => {
    const FormBlock = await importFormBlock();
    const html = renderToStaticMarkup(
      React.createElement(FormBlock, {
        block: {
          props: {
            fields: [
              {
                name: "ids",
                type: "multi-select" as const,
                label: "设备",
                options: [
                  { label: "SE-001", value: "SE-001", group: "A区" },
                  { label: "SE-002", value: "SE-002", group: "B区" },
                ],
              },
            ],
            default_values: { ids: [] },
          },
        },
      }),
    );
    expect(html).toContain("A区");
    expect(html).toContain("B区");
    expect(html).toContain("▼");
    expect(html).toContain("全不选");
  });

  it("returns null when submitted", async () => {
    const FormBlock = await importFormBlock();
    const html = renderToStaticMarkup(
      React.createElement(FormBlock, {
        block: {
          props: {
            fields: [
              { name: "x", type: "text" as const, label: "X" },
            ],
          },
          interactionState: { status: "submitted" as const },
        },
      }),
    );
    expect(html).toBe("");
  });

  it("shows expired message when expired", async () => {
    const FormBlock = await importFormBlock();
    const html = renderToStaticMarkup(
      React.createElement(FormBlock, {
        block: {
          props: {
            fields: [
              { name: "x", type: "text" as const, label: "X" },
            ],
          },
          interactionState: { status: "expired" as const },
        },
      }),
    );
    expect(html).toContain("expired");
  });
});
