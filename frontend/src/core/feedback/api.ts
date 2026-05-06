import { fetchGateway } from "@/core/api";
import { getBackendBaseURL } from "@/core/config";
import type { FeedbackSubmission, FeedbackSummary } from "./types";

export async function submitFeedback(data: FeedbackSubmission): Promise<{ success: boolean; id: string }> {
  const res = await fetchGateway(`${getBackendBaseURL()}/api/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? "Failed to submit feedback");
  }
  return res.json();
}

export async function getFeedbackSummary(params?: {
  start_date?: string;
  end_date?: string;
  tenant_id?: string;
}): Promise<FeedbackSummary> {
  const searchParams = new URLSearchParams();
  if (params?.start_date) searchParams.set("start_date", params.start_date);
  if (params?.end_date) searchParams.set("end_date", params.end_date);
  if (params?.tenant_id) searchParams.set("tenant_id", params.tenant_id);
  const qs = searchParams.toString();
  const url = `${getBackendBaseURL()}/api/feedback/summary${qs ? `?${qs}` : ""}`;
  const res = await fetchGateway(url);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? "Failed to fetch feedback summary");
  }
  return res.json();
}
