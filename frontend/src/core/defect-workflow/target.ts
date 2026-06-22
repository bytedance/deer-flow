import type { DefectWorkflowTodoRow } from "./types";

export interface DefectWorkflowDeepLinkTarget {
  taskId?: string | number | null;
  defectId?: string | number | null;
  defectNo?: string | number | null;
  autoOpen?: boolean;
}

export type DefectWorkflowTargetMatchBy = "task_id" | "defect_id" | "defect_no";

export interface DefectWorkflowTargetMatch {
  row: DefectWorkflowTodoRow;
  matchBy: DefectWorkflowTargetMatchBy;
}

function normalized(value: unknown): string | null {
  if (value === undefined || value === null) return null;
  const text = String(value).trim();
  return text ? text : null;
}

function equalsTarget(value: unknown, target: unknown): boolean {
  const left = normalized(value);
  const right = normalized(target);
  return left !== null && right !== null && left === right;
}

function defectIdCandidates(row: DefectWorkflowTodoRow): unknown[] {
  return [row.defect?.id, row.defect?.defectId];
}

function defectNoCandidates(row: DefectWorkflowTodoRow): unknown[] {
  return [row.defect?.defectNo, row.defect?.defectCode, row.defect?.code];
}

export function hasDefectWorkflowDeepLinkTarget(target: DefectWorkflowDeepLinkTarget | null | undefined): boolean {
  if (!target) return false;
  return Boolean(normalized(target.taskId) ?? normalized(target.defectId) ?? normalized(target.defectNo));
}

export function defectWorkflowDeepLinkTargetKey(target: DefectWorkflowDeepLinkTarget | null | undefined): string | null {
  if (!hasDefectWorkflowDeepLinkTarget(target)) return null;
  return [
    normalized(target?.taskId) ?? "",
    normalized(target?.defectId) ?? "",
    normalized(target?.defectNo) ?? "",
    target?.autoOpen ? "1" : "0",
  ].join("|");
}

export function findDefectWorkflowTargetRow(
  rows: DefectWorkflowTodoRow[],
  target: DefectWorkflowDeepLinkTarget | null | undefined,
): DefectWorkflowTargetMatch | null {
  if (!hasDefectWorkflowDeepLinkTarget(target)) return null;

  const taskMatch = rows.find((row) => equalsTarget(row.taskId, target?.taskId));
  if (taskMatch) return { row: taskMatch, matchBy: "task_id" };

  const defectIdMatch = rows.find((row) =>
    defectIdCandidates(row).some((candidate) => equalsTarget(candidate, target?.defectId)),
  );
  if (defectIdMatch) return { row: defectIdMatch, matchBy: "defect_id" };

  const defectNoMatch = rows.find((row) =>
    defectNoCandidates(row).some((candidate) => equalsTarget(candidate, target?.defectNo)),
  );
  if (defectNoMatch) return { row: defectNoMatch, matchBy: "defect_no" };

  return null;
}
