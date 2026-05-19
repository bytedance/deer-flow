/**
 * Closure-ticket types — match backend `closed_loop.schemas`
 * (see backend/packages/harness/deerflow/closed_loop/schemas.py).
 */

export type ClosureStatus =
  | "pending"
  | "assigned"
  | "in_progress"
  | "pending_verification"
  | "closed"
  | "rejected";

export type ClosurePriority = "urgent" | "important" | "normal" | "observe";

export type ClosureSourceType =
  | "diagnosis"
  | "daily_report"
  | "weekly_report"
  | "monthly_report"
  | "custom_report"
  | "manual";

export type ClosureAction =
  | "assign"
  | "start"
  | "submit_verification"
  | "verify_close"
  | "reject"
  | "mark_overdue";

export interface ClosureTicket {
  id: string;
  tenant_id: string;
  title: string;
  description: string | null;
  status: ClosureStatus;
  priority: ClosurePriority;
  severity: string | null;
  device_id: string | null;
  device_name: string | null;
  created_by: string;
  assignee_id: string | null;
  verifier_id: string | null;
  source_type: ClosureSourceType;
  source_run_id: string | null;
  source_thread_id: string | null;
  metadata: Record<string, unknown>;
  due_at: string | null;
  is_overdue: boolean;
  created_at: string;
  updated_at: string;
  assigned_at: string | null;
  started_at: string | null;
  submitted_at: string | null;
  closed_at: string | null;
}

export interface ClosureTicketEvent {
  id: string;
  ticket_id: string;
  action: ClosureAction | "create" | "update_metadata" | "overdue";
  from_status: ClosureStatus | null;
  to_status: ClosureStatus | null;
  actor_id: string | null;
  payload: Record<string, unknown>;
  occurred_at: string;
}

export interface PageMeta {
  total: number;
  page: number;
  page_size: number;
}

export interface ClosureTicketListResponse {
  items: ClosureTicket[];
  meta: PageMeta;
}

export interface ClosureNotificationsSummary {
  open: number;
  overdue: number;
  pending_verification: number;
  assigned_to_me: number;
}

export interface ListClosureTicketsParams {
  status?: ClosureStatus;
  statuses?: ClosureStatus[];
  device_id?: string;
  assignee_id?: string;
  created_by?: string;
  source_type?: ClosureSourceType;
  priority?: ClosurePriority;
  is_overdue?: boolean;
  created_at_gte?: string;
  created_at_lt?: string;
  closed_at_gte?: string;
  closed_at_lt?: string;
  due_at_gte?: string;
  due_at_lt?: string;
  page?: number;
  page_size?: number;
  order_by?: string;
  order_desc?: boolean;
}

export interface CreateClosureTicketRequest {
  title: string;
  description?: string;
  device_id?: string;
  device_name?: string;
  priority?: ClosurePriority;
  severity?: string;
  source_type: ClosureSourceType;
  source_run_id?: string;
  source_thread_id?: string;
  metadata?: Record<string, unknown>;
}

export interface UpdateClosureTicketRequest {
  title?: string;
  description?: string;
  priority?: ClosurePriority;
  severity?: string;
  assignee_id?: string;
  device_name?: string;
  metadata_patch?: Record<string, unknown>;
}

export interface TransitionClosureTicketRequest {
  action: ClosureAction;
  payload?: Record<string, unknown>;
}
