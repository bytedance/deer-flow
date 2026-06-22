import { describe, expect, it } from "vitest";

import { validateProps } from "@/core/genui/validator";

describe("validateProps form multi-select", () => {
  const baseForm = {
    fields: [
      {
        name: "equipment_ids",
        type: "multi-select" as const,
        label: "设备列表",
        options: [
          { label: "SE-001", value: "SE-001", group: "A区", description: "换热器-001" },
          { label: "SE-002", value: "SE-002", group: "B区" },
        ],
        searchable: true,
        max_visible: 10,
      },
    ],
    default_values: { equipment_ids: ["SE-001", "SE-002"] },
    submit_label: "下一步",
  };

  it("accepts valid multi-select field", () => {
    const result = validateProps("form", baseForm);
    expect(result.success).toBe(true);
  });

  it("accepts multi-select without optional fields", () => {
    const result = validateProps("form", {
      fields: [
        {
          name: "ids",
          type: "multi-select",
          label: "Select",
          options: [{ label: "A", value: "a" }],
        },
      ],
    });
    expect(result.success).toBe(true);
  });

  it("accepts options with group only", () => {
    const result = validateProps("form", {
      fields: [
        {
          name: "ids",
          type: "multi-select",
          label: "Select",
          options: [{ label: "A", value: "a", group: "G1" }],
        },
      ],
    });
    expect(result.success).toBe(true);
  });

  it("accepts options with description only", () => {
    const result = validateProps("form", {
      fields: [
        {
          name: "ids",
          type: "multi-select",
          label: "Select",
          options: [{ label: "A", value: "a", description: "desc" }],
        },
      ],
    });
    expect(result.success).toBe(true);
  });

  it("rejects invalid field type", () => {
    const result = validateProps("form", {
      fields: [
        { name: "x", type: "unknown-type", label: "X" },
      ],
    });
    expect(result.success).toBe(false);
  });

  it("accepts max_visible = 1", () => {
    const result = validateProps("form", {
      fields: [
        {
          name: "ids",
          type: "multi-select",
          label: "Select",
          max_visible: 1,
        },
      ],
    });
    expect(result.success).toBe(true);
  });

  it("rejects max_visible = 0", () => {
    const result = validateProps("form", {
      fields: [
        {
          name: "ids",
          type: "multi-select",
          label: "Select",
          max_visible: 0,
        },
      ],
    });
    expect(result.success).toBe(false);
  });
});

describe("validateProps form existing types unchanged", () => {
  it("accepts text field", () => {
    const result = validateProps("form", {
      fields: [{ name: "x", type: "text", label: "X" }],
    });
    expect(result.success).toBe(true);
  });

  it("accepts select field with options", () => {
    const result = validateProps("form", {
      fields: [
        {
          name: "x",
          type: "select",
          label: "X",
          options: [{ label: "A", value: "a" }],
        },
      ],
    });
    expect(result.success).toBe(true);
  });

  it("accepts checkbox field", () => {
    const result = validateProps("form", {
      fields: [{ name: "x", type: "checkbox", label: "X" }],
    });
    expect(result.success).toBe(true);
  });

  it("accepts date field", () => {
    const result = validateProps("form", {
      fields: [{ name: "x", type: "date", label: "X" }],
    });
    expect(result.success).toBe(true);
  });
});

describe("validateProps direction normalization", () => {
  it.each(["neutral", "stable", "unchanged", "none", "same"])(
    "card: normalizes '%s' → 'flat' in trend.direction",
    (synonym) => {
      const result = validateProps("card", {
        title: "KPI",
        value: "92%",
        trend: { direction: synonym, value: "0%" },
      });
      expect(result.success).toBe(true);
    },
  );

  it.each(["rising", "increasing"])(
    "card: normalizes '%s' → 'up' in trend.direction",
    (synonym) => {
      const result = validateProps("card", {
        title: "KPI",
        value: "92%",
        trend: { direction: synonym, value: "+5%" },
      });
      expect(result.success).toBe(true);
    },
  );

  it.each(["falling", "decreasing"])(
    "card: normalizes '%s' → 'down' in trend.direction",
    (synonym) => {
      const result = validateProps("card", {
        title: "KPI",
        value: "88%",
        trend: { direction: synonym, value: "-3%" },
      });
      expect(result.success).toBe(true);
    },
  );

  it("metric: normalizes 'neutral' → 'flat' in delta.direction", () => {
    const result = validateProps("metric", {
      value: 128.4,
      delta: { value: "0", direction: "neutral" },
    });
    expect(result.success).toBe(true);
  });

  it("rejects genuinely invalid direction values", () => {
    const result = validateProps("card", {
      title: "KPI",
      value: "92%",
      trend: { direction: "sideways", value: "0%" },
    });
    expect(result.success).toBe(false);
  });
});

describe("validateProps defect workflow todo list", () => {
  it("accepts deep-link target props", () => {
    const result = validateProps("defect-workflow-todo-list", {
      title: "缺陷待办",
      page_size: 20,
      selected_task_id: null,
      target_task_id: "90457",
      target_defect_id: 1782112299446001,
      target_defect_no: "QX20260622-A2A4AA30",
      auto_open_detail: true,
    });

    expect(result.success).toBe(true);
  });
});
