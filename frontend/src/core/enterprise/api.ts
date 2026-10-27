import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export type Target = {
  id: string;
  name: string;
  provider: string;
  enabled: boolean;
};
export type Receipt = {
  id: string;
  target_name: string;
  status: "sending" | "sent" | "failed" | "unknown";
  error: string | null;
  created_at?: string;
};
export type Overview = {
  targets: Target[];
  deliveries: Receipt[];
  scheduler_enabled: boolean;
};

export async function enterpriseRequest<T>(
  path: string,
  body?: unknown,
  method = "POST",
): Promise<T> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/enterprise${path}`,
    body === undefined && method === "POST"
      ? undefined
      : {
          method,
          headers: { "Content-Type": "application/json" },
          body: body === undefined ? undefined : JSON.stringify(body),
        },
  );
  if (!response.ok) {
    const data = (await response.json().catch(() => null)) as {
      detail?: { code?: string };
    } | null;
    throw new Error(data?.detail?.code ?? "request_failed");
  }
  return response.json() as Promise<T>;
}

export function buildSchedule(mode: string, value: string) {
  return mode === "once"
    ? {
        schedule_type: "once",
        schedule_spec: { run_at: value },
        timezone: "Asia/Shanghai",
      }
    : {
        schedule_type: "cron",
        schedule_spec: { cron: mode === "weekdays" ? "0 9 * * 1-5" : value },
        timezone: "Asia/Shanghai",
      };
}
