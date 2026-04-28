import type { GlobalVariable } from "./types";

const API_BASE = "/api/global-variables";

export type VariablesListResponse = {
  variables: GlobalVariable[];
  lastUpdated: string;
};

export type VariableSetRequest = {
  value: string;
  description?: string;
  llm_editable?: boolean;
};

export async function fetchProjectVariables(): Promise<VariablesListResponse> {
  const res = await fetch(`${API_BASE}/project`);
  if (!res.ok)
    throw new Error(`Failed to fetch project variables: ${res.statusText}`);
  return res.json();
}

export async function fetchThreadVariables(
  threadId: string,
): Promise<VariablesListResponse> {
  const res = await fetch(`${API_BASE}/threads/${threadId}`);
  if (!res.ok)
    throw new Error(`Failed to fetch thread variables: ${res.statusText}`);
  return res.json();
}

export async function setProjectVariable(
  key: string,
  request: VariableSetRequest,
): Promise<VariablesListResponse> {
  const res = await fetch(`${API_BASE}/project/${encodeURIComponent(key)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || "Failed to set variable");
  }
  return res.json();
}

export async function setThreadVariable(
  threadId: string,
  key: string,
  request: VariableSetRequest,
): Promise<VariablesListResponse> {
  const res = await fetch(
    `${API_BASE}/threads/${threadId}/${encodeURIComponent(key)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || "Failed to set variable");
  }
  return res.json();
}

export async function deleteProjectVariable(
  key: string,
): Promise<VariablesListResponse> {
  const res = await fetch(`${API_BASE}/project/${encodeURIComponent(key)}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || "Failed to delete variable");
  }
  return res.json();
}

export async function deleteThreadVariable(
  threadId: string,
  key: string,
): Promise<VariablesListResponse> {
  const res = await fetch(
    `${API_BASE}/threads/${threadId}/${encodeURIComponent(key)}`,
    {
      method: "DELETE",
    },
  );
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(error.detail || "Failed to delete variable");
  }
  return res.json();
}
