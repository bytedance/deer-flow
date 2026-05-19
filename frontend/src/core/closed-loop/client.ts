import { fetchGateway } from "@/core/api";
import { getBackendBaseURL } from "@/core/config";

import type {
  ClosureNotificationsSummary,
  ClosureTicket,
  ClosureTicketEvent,
  ClosureTicketListResponse,
  CreateClosureTicketRequest,
  ListClosureTicketsParams,
  TransitionClosureTicketRequest,
  UpdateClosureTicketRequest,
} from "./types";

function _buildQuery(params: ListClosureTicketsParams | undefined): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) {
      for (const v of value) search.append(key, String(v));
    } else if (typeof value === "boolean") {
      search.append(key, value ? "true" : "false");
    } else {
      search.append(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

async function _readError(res: Response): Promise<string> {
  const text = await res.text().catch(() => "");
  if (!text) return res.statusText;
  try {
    const parsed = JSON.parse(text) as { detail?: string; message?: string };
    return parsed.detail ?? parsed.message ?? text;
  } catch {
    return text;
  }
}

export async function listClosureTickets(
  params?: ListClosureTicketsParams,
): Promise<ClosureTicketListResponse> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/closure/tickets${_buildQuery(params)}`,
  );
  if (!res.ok) {
    throw new Error(`Failed to list closure tickets: ${await _readError(res)}`);
  }
  return res.json() as Promise<ClosureTicketListResponse>;
}

export async function getClosureTicket(ticketId: string): Promise<ClosureTicket> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/closure/tickets/${ticketId}`,
  );
  if (!res.ok) {
    throw new Error(`Failed to load ticket ${ticketId}: ${await _readError(res)}`);
  }
  return res.json() as Promise<ClosureTicket>;
}

export async function listClosureTicketEvents(
  ticketId: string,
): Promise<ClosureTicketEvent[]> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/closure/tickets/${ticketId}/events`,
  );
  if (!res.ok) {
    throw new Error(`Failed to load events: ${await _readError(res)}`);
  }
  const body = (await res.json()) as
    | { events: ClosureTicketEvent[] }
    | ClosureTicketEvent[];
  return Array.isArray(body) ? body : body.events;
}

export async function createClosureTicket(
  request: CreateClosureTicketRequest,
): Promise<ClosureTicket> {
  const res = await fetchGateway(`${getBackendBaseURL()}/api/closure/tickets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!res.ok) {
    throw new Error(`Failed to create ticket: ${await _readError(res)}`);
  }
  return res.json() as Promise<ClosureTicket>;
}

export async function updateClosureTicket(
  ticketId: string,
  request: UpdateClosureTicketRequest,
): Promise<ClosureTicket> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/closure/tickets/${ticketId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  if (!res.ok) {
    throw new Error(`Failed to update ticket: ${await _readError(res)}`);
  }
  return res.json() as Promise<ClosureTicket>;
}

export async function transitionClosureTicket(
  ticketId: string,
  request: TransitionClosureTicketRequest,
): Promise<ClosureTicket> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/closure/tickets/${ticketId}/transition`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
  if (!res.ok) {
    throw new Error(`Failed to transition ticket: ${await _readError(res)}`);
  }
  return res.json() as Promise<ClosureTicket>;
}

export async function getClosureNotificationsSummary(): Promise<ClosureNotificationsSummary> {
  const res = await fetchGateway(
    `${getBackendBaseURL()}/api/closure/notifications/summary`,
  );
  if (!res.ok) {
    throw new Error(`Failed to load summary: ${await _readError(res)}`);
  }
  return res.json() as Promise<ClosureNotificationsSummary>;
}
