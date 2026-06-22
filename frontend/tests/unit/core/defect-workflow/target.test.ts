import { describe, expect, it } from "vitest";

import {
  defectWorkflowDeepLinkTargetKey,
  findDefectWorkflowTargetRow,
  hasDefectWorkflowDeepLinkTarget,
  type DefectWorkflowTodoRow,
} from "@/core/defect-workflow";

const rows: DefectWorkflowTodoRow[] = [
  {
    taskId: "task-a",
    nodeName: "班长确认",
    defect: {
      id: "defect-a",
      defectId: "legacy-defect-a",
      defectNo: "QX-A",
      defectCode: "CODE-A",
      title: "缺陷 A",
    },
  },
  {
    taskId: "task-b",
    nodeName: "工程师确认",
    defect: {
      id: "defect-b",
      defectId: "legacy-defect-b",
      defectNo: "QX-B",
      defectCode: "CODE-B",
      title: "缺陷 B",
    },
  },
  {
    taskId: "task-c",
    nodeName: "缺陷验收",
    defect: {
      id: "defect-c",
      defectId: "legacy-defect-c",
      code: "CODE-C",
      title: "缺陷 C",
    },
  },
];

describe("defect workflow deep-link target matching", () => {
  it("reports whether a target contains any usable identifier", () => {
    expect(hasDefectWorkflowDeepLinkTarget(null)).toBe(false);
    expect(hasDefectWorkflowDeepLinkTarget({ taskId: "  " })).toBe(false);
    expect(hasDefectWorkflowDeepLinkTarget({ defectNo: "QX-A" })).toBe(true);
  });

  it("builds a stable target key", () => {
    expect(defectWorkflowDeepLinkTargetKey({
      taskId: "task-a",
      defectId: "defect-a",
      defectNo: "QX-A",
      autoOpen: true,
    })).toBe("task-a|defect-a|QX-A|1");
  });

  it("prefers task id over defect id and defect number", () => {
    const match = findDefectWorkflowTargetRow(rows, {
      taskId: "task-b",
      defectId: "defect-a",
      defectNo: "QX-A",
    });

    expect(match?.matchBy).toBe("task_id");
    expect(match?.row.taskId).toBe("task-b");
  });

  it("falls back to defect id when task id is absent or unmatched", () => {
    const match = findDefectWorkflowTargetRow(rows, {
      taskId: "missing-task",
      defectId: "legacy-defect-a",
      defectNo: "QX-B",
    });

    expect(match?.matchBy).toBe("defect_id");
    expect(match?.row.taskId).toBe("task-a");
  });

  it("falls back to defect number/code when task and defect id do not match", () => {
    const match = findDefectWorkflowTargetRow(rows, {
      taskId: "missing-task",
      defectId: "missing-defect",
      defectNo: "CODE-C",
    });

    expect(match?.matchBy).toBe("defect_no");
    expect(match?.row.taskId).toBe("task-c");
  });

  it("returns null when no loaded row matches", () => {
    expect(findDefectWorkflowTargetRow(rows, {
      taskId: "missing-task",
      defectId: "missing-defect",
      defectNo: "missing-no",
    })).toBeNull();
  });
});
