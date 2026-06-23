import { describe, expect, it } from "vitest";

import { sanitizeProps } from "@/core/genui/sanitizer";
import { validateProps } from "@/core/genui/validator";

describe("sanitizeProps defect workflow todo list", () => {
  it("keeps deep-link target props and strips disallowed callbacks", () => {
    const sanitized = sanitizeProps("defect-workflow-todo-list", {
      title: "缺陷待办",
      page_size: 20,
      selected_task_id: "90457",
      target_task_id: "90457",
      target_defect_id: "1782112299446001",
      target_defect_no: "QX20260622-A2A4AA30",
      auto_open_detail: true,
      onSelect: () => undefined,
    });

    expect(sanitized).toEqual({
      title: "缺陷待办",
      page_size: 20,
      selected_task_id: "90457",
      target_task_id: "90457",
      target_defect_id: "1782112299446001",
      target_defect_no: "QX20260622-A2A4AA30",
      auto_open_detail: true,
    });
  });
});

describe("sanitizeProps timeline", () => {
  it("fills missing event titles from common workflow fields", () => {
    const sanitized = sanitizeProps("timeline", {
      title: "历史处理记录",
      events: [
        {
          nodeName: "班长确认",
          action: "通过",
          operator: "user02",
          timestamp: "6/22 15:12",
          status: "success",
        },
        {
          node: "工程师确认",
          operation: "驳回",
          time: "6/22 15:12",
          status: "rejected",
        },
        {
          remark: "缺陷分类改为二类后重提",
        },
      ],
    });

    expect(sanitized).toMatchObject({
      title: "历史处理记录",
      events: [
        {
          title: "班长确认 - 通过",
          timestamp: "6/22 15:12",
          status: "completed",
        },
        {
          title: "工程师确认 - 驳回",
          timestamp: "6/22 15:12",
        },
        {
          title: "事件 3",
        },
      ],
    });
    expect(validateProps("timeline", sanitized).success).toBe(true);
  });
});
