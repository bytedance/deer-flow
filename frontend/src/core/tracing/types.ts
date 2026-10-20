export type TracingProvider = "arize" | "langsmith" | "langfuse";
export type TracingMode = "inherit" | "disabled" | "configured";

export interface TracingDestination {
  provider: TracingProvider;
  endpoint?: string | null;
  project?: string | null;
  space_id?: string | null;
  workspace_id?: string | null;
}

export interface TracingProviderConfig extends TracingDestination {
  public_key?: string | null;
  transport?: "http" | "grpc";
  has_api_key: boolean;
  has_secret_key: boolean;
}

export interface TracingProfile {
  id: string;
  name: string;
  revision: number;
  providers: TracingProviderConfig[];
  allowed_user_ids: string[];
}

export interface TracingProfilesResponse {
  profiles: TracingProfile[];
  can_manage: boolean;
  available: boolean;
  reason: string | null;
}

export interface AgentTracing {
  mode: TracingMode;
  profile_id: string | null;
  revision: number;
  effective_revision: string;
  source: string;
  destinations: TracingDestination[];
  status: "active" | "unavailable" | "degraded" | "pending";
  error: string | null;
  delivery_verified: false;
  can_select: boolean;
}

export interface SaveAgentTracingRequest {
  mode: TracingMode;
  profile_id: string | null;
  expected_revision: number;
}

export interface TracingProviderInput extends TracingDestination {
  public_key?: string;
  transport?: "http" | "grpc";
  api_key?: string;
  secret_key?: string;
}

export interface SaveTracingProfileRequest {
  name: string;
  providers: TracingProviderInput[];
  allowed_user_ids: string[];
  expected_revision: number;
}
