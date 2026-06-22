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

  it("switches the detail panel when another todo row is selected", async () => {
    const { default: DefectWorkflowTodoListBlock } = await import("@/components/genui/DefectWorkflowTodoListBlock");
    mocks.listDefectWorkflowTodos.mockResolvedValue({
      rows: [
        {
          taskId: "90055",
          nodeName: "工程师确认",
          allowedActions: ["SUBMIT"],
          claimedByCurrentUser: true,
          defect: {
            defectId: "defect-001",
            defectCode: "QX-001",
            title: "第一条缺陷",
            status: "CONFIRMING",
            equipment: { deviceName: "P-101" },
          },
        },
        {
          taskId: "90056",
          nodeName: "班长确认",
          allowedActions: ["SUBMIT"],
          claimedByCurrentUser: true,
          defect: {
            defectId: "defect-002",
            defectCode: "QX-002",
            title: "第二条缺陷",
            status: "TREATING",
            equipment: { deviceName: "P-102" },
          },
        },
      ],
      total: 2,
    });
    mocks.getDefectWorkflowDetail.mockImplementation((defectId: string | number) => Promise.resolve({
      defect: {
        id: defectId,
        title: String(defectId) === "defect-002" ? "第二条缺陷" : "第一条缺陷",
        status: String(defectId) === "defect-002" ? "TREATING" : "CONFIRMING",
        equipment: { deviceName: String(defectId) === "defect-002" ? "P-102" : "P-101" },
      },
      currentTask: {
        taskId: String(defectId) === "defect-002" ? "90056" : "90055",
        nodeName: String(defectId) === "defect-002" ? "班长确认" : "工程师确认",
        allowedActions: ["SUBMIT"],
        claimedByCurrentUser: true,
      },
    }));
    mocks.getDefectWorkflowFormContext.mockImplementation((taskId: string | number) => Promise.resolve({
      formSchema: {
        widgetList: [
          {
            type: "textarea",
            options: {
              name: "treatmentPlan",
              label: "处理方案",
            },
          },
        ],
      },
      effectiveFormData: { treatmentPlan: String(taskId) === "90056" ? "第二方案" : "第一方案" },
    }));

    React.act(() => {
      root.render(
        React.createElement(DefectWorkflowTodoListBlock, {
          block: {
            block_id: "defect-workflow-closure:todo-list:test-thread",
            props: {
              title: "缺陷待办",
              page_size: 5,
              target_task_id: "90055",
              target_defect_id: "defect-001",
              target_defect_no: "QX-001",
              auto_open_detail: true,
            },
          },
        }),
      );
    });
    await flushEffects();

    const detailButtons = Array.from(container.querySelectorAll("button"))
      .filter((button) => button.textContent?.includes("详情"));
    expect(detailButtons).toHaveLength(2);

    React.act(() => {
      detailButtons[0]?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await flushEffects();
    expect((container.querySelector("textarea") as HTMLTextAreaElement).value).toBe("第一方案");

    React.act(() => {
      detailButtons[1]?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await flushEffects();

    expect(mocks.getDefectWorkflowDetail).toHaveBeenCalledWith("defect-002");
    expect(mocks.getDefectWorkflowFormContext).toHaveBeenCalledWith("90056");
    expect(container.textContent).toContain("任务：90056");
    expect((container.querySelector("textarea") as HTMLTextAreaElement).value).toBe("第二方案");
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

  it("auto-opens the target detail from deep-link task props", async () => {
    const { default: DefectWorkflowTodoListBlock } = await import("@/components/genui/DefectWorkflowTodoListBlock");
    mocks.listDefectWorkflowTodos.mockResolvedValue({
      rows: [
        {
          taskId: "90054",
          nodeName: "班长确认",
          claimedByCurrentUser: true,
          defect: {
            defectId: "1781744317660001",
            defectCode: "QX-OTHER",
            title: "其他缺陷",
            equipment: { deviceName: "P-100" },
          },
        },
        {
          taskId: "90055",
          nodeName: "维修处理",
          allowedActions: ["SUBMIT", "REJECT"],
          claimedByCurrentUser: true,
          defect: {
            defectId: "1781744317660016",
            defectCode: "QX20260618-678EC4CF",
            title: "泵密封泄漏",
            equipment: { deviceName: "P-101" },
          },
        },
      ],
      total: 2,
    });

    React.act(() => {
      root.render(
        React.createElement(DefectWorkflowTodoListBlock, {
          block: {
            block_id: "defect-workflow-closure:todo-list:test-thread",
            props: {
              title: "缺陷待办",
              page_size: 5,
              target_task_id: "90055",
              target_defect_id: "1781744317660016",
              target_defect_no: "QX20260618-678EC4CF",
              auto_open_detail: true,
            },
          },
        }),
      );
    });
    await flushEffects();
    await flushEffects();

    expect(mocks.getDefectWorkflowDetail).toHaveBeenCalledWith("1781744317660016");
    expect(mocks.getDefectWorkflowFormContext).toHaveBeenCalledWith("90055");
    expect(container.textContent).toContain("维修方案");
    expect((container.querySelector("textarea") as HTMLTextAreaElement).value).toBe("原方案");
  });

  it("shows a not-found notice without opening detail when target is not in loaded todos", async () => {
    const { default: DefectWorkflowTodoListBlock } = await import("@/components/genui/DefectWorkflowTodoListBlock");

    React.act(() => {
      root.render(
        React.createElement(DefectWorkflowTodoListBlock, {
          block: {
            block_id: "defect-workflow-closure:todo-list:test-thread",
            props: {
              title: "缺陷待办",
              page_size: 5,
              target_task_id: "missing-task",
              target_defect_id: "missing-defect",
              target_defect_no: "QX-MISSING",
              auto_open_detail: true,
            },
          },
        }),
      );
    });
    await flushEffects();

    expect(container.textContent).toContain("未在当前待办列表中找到从 EHM 跳转过来的缺陷 QX-MISSING");
    expect(mocks.getDefectWorkflowDetail).not.toHaveBeenCalled();
    expect(mocks.getDefectWorkflowFormContext).not.toHaveBeenCalled();
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
