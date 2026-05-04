export interface AdminStats {
  total_tenants: number;
  active_tenants_today: number;
  total_threads: number;
  total_llm_calls_today: number;
  total_tokens_today: number;
  total_cost_today: number;
  total_cost_month: number;
}

export interface TenantSummary {
  tenant_id: string;
  name: string;
  created_at: string;
  user_count: number;
  thread_count: number;
  cost_today: number;
  cost_month: number;
  is_active: boolean;
}

export interface CreateTenantRequest {
  tenant_id: string;
  name: string;
}

export interface UpdateTenantRequest {
  name?: string;
}

export interface UsageRecord {
  timestamp: string;
  tenant_id: string;
  thread_id: string | null;
  model_name: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number;
}

export interface CostSummary {
  today_cost_usd: number;
  month_cost_usd: number;
  total_cost_usd: number;
  today_tokens: number;
  month_tokens: number;
}

export interface CostBreakdownItem {
  date: string;
  model_name: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface BudgetStatus {
  daily_cost: number;
  daily_limit: number;
  daily_remaining: number;
  daily_pct: number;
  monthly_cost: number;
  monthly_limit: number;
  monthly_remaining: number;
  monthly_pct: number;
  is_exceeded: boolean;
  alert_triggered: boolean;
}

export interface UpdateBudgetRequest {
  daily_limit_usd?: number;
  monthly_limit_usd?: number;
  alert_threshold_pct?: number;
  action_on_exceed?: string;
}

export interface AuditLogEntry {
  timestamp: string;
  tenant_id: string;
  thread_id: string | null;
  direction: string;
  role: string;
  original_text: string;
  sanitized_text: string | null;
  allowed: boolean;
  flagged_categories: string[];
  reasons: string[];
  provider: string;
}

export interface AuditLogResponse {
  entries: AuditLogEntry[];
  total: number;
  limit: number;
  offset: number;
}
