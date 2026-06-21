import { fetchGateway } from "@/core/api";
import { getBackendBaseURL } from "@/core/config";

import type {
  DefectWorkflowApiEnvelope,
  DefectWorkflowDetail,
  DefectWorkflowPage,
  DefectWorkflowTodoParams,
  DefectWorkflowTodoRow,
  SubmitDefectWorkflowTaskRequest,
  WorkflowTaskFormContext,
} from "./types";

const API_PREFIX = `${getBackendBaseURL()}/api/defect-workflow`;

function buildQuery(params?: Record<string, string | number | boolean | undefined>): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) continue;
    search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

async function readBody(res: Response): Promise<unknown> {
  const text = await res.text().catch(() => "");
  if (!text) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function unwrapData<T>(body: unknown): T {
  if (
    typeof body === "object" &&
    body !== null &&
    "data" in body
  ) {
    return (body as DefectWorkflowApiEnvelope<T>).data as T;
  }
  return body as T;
}

function errorMessage(body: unknown, fallback: string): string {
  if (typeof body === "string") return body || fallback;
  if (typeof body !== "object" || body === null) return fallback;
  const record = body as Record<string, unknown>;
  const detail = record.detail;
  if (typeof detail === "string") return detail;
  if (typeof detail === "object" && detail !== null) {
    const detailRecord = detail as Record<string, unknown>;
    return String(detailRecord.message ?? detailRecord.code ?? fallback);
  }
  return String(record.message ?? record.msg ?? fallback);
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetchGateway(`${API_PREFIX}${path}`, init);
  const body = await readBody(res);
  if (!res.ok) {
    throw new Error(errorMessage(body, res.statusText));
  }
  return unwrapData<T>(body);
}

export async function listDefectWorkflowTodos(
  params?: DefectWorkflowTodoParams,
): Promise<DefectWorkflowPage<DefectWorkflowTodoRow>> {
  const data = await requestJson<DefectWorkflowPage<DefectWorkflowTodoRow> | DefectWorkflowTodoRow[]>(
    `/tasks/todo${buildQuery(params)}`,
  );
  return Array.isArray(data) ? { rows: data } : data;
}

export function getDefectWorkflowDetail(
  defectId: string | number,
): Promise<DefectWorkflowDetail> {
  return requestJson<DefectWorkflowDetail>(
    `/defects/${encodeURIComponent(String(defectId))}`,
  );
}

export function getDefectWorkflowFormContext(
  taskId: string | number,
): Promise<WorkflowTaskFormContext> {
  return requestJson<WorkflowTaskFormContext>(
    `/tasks/${encodeURIComponent(String(taskId))}/form-context`,
  );
}

export function claimDefectWorkflowTask(
  defectId: string | number,
  taskId: string | number,
  comment?: string,
): Promise<unknown> {
  return requestJson<unknown>(
    `/defects/${encodeURIComponent(String(defectId))}/workflow-tasks/${encodeURIComponent(String(taskId))}/claim`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ comment }),
    },
  );
}

export function submitDefectWorkflowTask(
  defectId: string | number,
  taskId: string | number,
  request: SubmitDefectWorkflowTaskRequest,
): Promise<unknown> {
  return requestJson<unknown>(
    `/defects/${encodeURIComponent(String(defectId))}/workflow-tasks/${encodeURIComponent(String(taskId))}/submit`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
}
