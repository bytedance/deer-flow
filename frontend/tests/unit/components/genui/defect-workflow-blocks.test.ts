/* @vitest-environment jsdom */

import React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  listDefectWorkflowTodos: vi.fn(),
  getDefectWorkflowDetail: vi.fn(),
  getDefectWorkflowFormContext: vi.fn(),
  claimDefectWorkflowTask: vi.fn(),
  submitDefectWorkflowTask: vi.fn(),
}));

vi.mock("@/core/defect-workflow", async () => {
  const actual = await vi.importActual("@/core/defect-workflow");
  return {
    ...actual,
    listDefectWorkflowTodos: mocks.listDefectWorkflowTodos,
    getDefectWorkflowDetail: mocks.getDefectWorkflowDetail,
    getDefectWorkflowFormContext: mocks.getDefectWorkflowFormContext,
    claimDefectWorkflowTask: mocks.claimDefectWorkflowTask,
    submitDefectWorkflowTask: mocks.submitDefectWorkflowTask,
  };
});

async function flushEffects() {
  await React.act(async () => {
    await Promise.resolve();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("DefectWorkflowTodoListBlock", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    mocks.listDefectWorkflowTodos.mockResolvedValue({
      rows: [
        {
          taskId: "90055",
          nodeName: "维修处理",
          allowedActions: ["SUBMIT", "REJECT"],
          claimedByCurrentUser: true,
          defect: {
            defectId: "1781744317660016",
            defectCode: "DF-001",
            title: "泵密封泄漏",
            status: "processing",
            equipment: { deviceName: "P-101" },
          },
        },
      ],
      total: 1,
    });
    mocks.getDefectWorkflowDetail.mockResolvedValue({
      defect: {
        id: "1781744317660016",
        title: "泵密封泄漏",
        status: "processing",
        equipment: { deviceName: "P-101" },
      },
      currentTask: {
        taskId: "90055",
        nodeName: "维修处理",
        allowedActions: ["SUBMIT", "REJECT"],
        claimedByCurrentUser: true,
      },
    });
    mocks.getDefectWorkflowFormContext.mockResolvedValue({
      formSchema: {
        widgetList: [
          {
            type: "textarea",
            options: {
              name: "maintenancePlan",
              label: "维修方案",
              required: true,
            },
          },
        ],
      },
      effectiveFormData: { maintenancePlan: "原方案" },
    });
  });

  afterEach(() => {
    React.act(() => root.unmount());
    container.remove();
    vi.clearAllMocks();
  });

  it("loads todos, opens detail, and keeps form data after submit error", async () => {
    const { default: DefectWorkflowTodoListBlock } = await import("@/components/genui/DefectWorkflowTodoListBlock");
    mocks.submitDefectWorkflowTask.mockRejectedValue(new Error("平台提交失败"));

    React.act(() => {
      root.render(
        React.createElement(DefectWorkflowTodoListBlock, {
          block: {
            block_id: "defect-workflow-closure:todo-list:test-thread",
            props: { title: "缺陷待办", page_size: 5 },
          },
        }),
      );
    });
    await flushEffects();

    expect(container.textContent).toContain("泵密封泄漏");
    expect(container.textContent).toContain("P-101");

    const detailButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent?.includes("详情"));
    expect(detailButton).toBeTruthy();
    React.act(() => {
      detailButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await flushEffects();

    const textarea = container.querySelector("textarea") as HTMLTextAreaElement;
    expect(textarea.value).toBe("原方案");
    React.act(() => {
      const valueSetter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype,
        "value",
      )?.set;
      valueSetter?.call(textarea, "更新后的维修方案");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });

    const submitButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent?.includes("通过"));
    expect(submitButton).toBeTruthy();
    React.act(() => {
      submitButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await flushEffects();

    expect(mocks.submitDefectWorkflowTask).toHaveBeenCalledWith(
      "1781744317660016",
      "90055",
      expect.objectContaining({ action: "SUBMIT" }),
    );
    expect(container.textContent).toContain("平台提交失败");
    expect((container.querySelector("textarea") as HTMLTextAreaElement).value).toBe("更新后的维修方案");
  });

  it("restores the selected detail from block props after remount", async () => {
    const { default: DefectWorkflowTodoListBlock } = await import("@/components/genui/DefectWorkflowTodoListBlock");

    React.act(() => {
      root.render(
        React.createElement(DefectWorkflowTodoListBlock, {
          block: {
            block_id: "defect-workflow-closure:todo-list:test-thread",
            props: {
              title: "缺陷待办",
              page_size: 5,
              selected_task_id: "90055",
            },
          },
        }),
      );
    });
    await flushEffects();

    expect(container.textContent).toContain("维修处理");
    expect(container.textContent).toContain("维修方案");
    expect((container.querySelector("textarea") as HTMLTextAreaElement).value).toBe("原方案");
  });

  it("hides current task form until a pending-claim task is claimed", async () => {
    const { default: DefectWorkflowTodoListBlock } = await import("@/components/genui/DefectWorkflowTodoListBlock");
    mocks.listDefectWorkflowTodos.mockResolvedValue({
      rows: [
        {
          taskId: "90103",
          nodeName: "缺陷验收",
          claimable: true,
          claimedByCurrentUser: false,
          allowedActions: ["SUBMIT"],
          defect: {
            defectId: "1781744317660112",
            defectCode: "QX20260618-678EC4CF",
            title: "测试ehm设备01 11",
            status: "ACCEPTING",
            equipment: { deviceName: "测试ehm设备01" },
          },
        },
      ],
      total: 1,
    });
    mocks.getDefectWorkflowDetail.mockResolvedValue({
      defect: {
        id: "1781744317660112",
        title: "测试ehm设备01 11",
        status: "ACCEPTING",
        equipment: { deviceName: "测试ehm设备01" },
      },
      currentTask: {
        taskId: "90103",
        nodeName: "缺陷验收",
        claimable: true,
        claimedByCurrentUser: false,
        allowedActions: ["SUBMIT"],
      },
      submissions: [
        {
          taskId: "90120",
          nodeName: "班长确认",
          action: "SUBMIT",
          formData: JSON.stringify({ shutdownRequired: true }),
        },
      ],
    });
    mocks.getDefectWorkflowFormContext.mockImplementation((taskId: string | number) => {
      if (String(taskId) === "90120") {
        return Promise.resolve({
          form: {
            formJson: {
              widgetList: [
                {
                  type: "switch",
                  options: { name: "shutdownRequired", label: "是否需要停机" },
                },
              ],
            },
          },
        });
      }
      return Promise.resolve({
        form: {
          formJson: {
            widgetList: [
              {
                type: "textarea",
                options: { name: "treatmentEffect", label: "处理效果" },
              },
            ],
          },
        },
        effectiveFormData: { treatmentEffect: "待验收" },
        allowedActions: ["SUBMIT"],
      });
    });

    React.act(() => {
      root.render(
        React.createElement(DefectWorkflowTodoListBlock, {
          block: {
            block_id: "defect-workflow-closure:todo-list:test-thread",
            props: { title: "缺陷待办", page_size: 5 },
          },
        }),
      );
    });
    await flushEffects();

    const detailButton = Array.from(container.querySelectorAll("button"))
      .find((button) => button.textContent?.includes("详情"));
    React.act(() => {
      detailButton?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await flushEffects();

    expect(container.textContent).toContain("历史处理记录");
    expect(container.textContent).toContain("是否需要停机");
    expect(container.textContent).toContain("待认领");
    expect(container.textContent).toContain("认领");
    expect(container.textContent).not.toContain("处理效果");
    expect(container.querySelector("textarea")).toBeNull();
  });
});
