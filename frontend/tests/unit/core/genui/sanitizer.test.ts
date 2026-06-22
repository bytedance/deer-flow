import { describe, expect, it } from "vitest";

import { sanitizeProps } from "@/core/genui/sanitizer";

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
