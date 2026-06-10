export type ChannelProviderId = "telegram" | "slack" | "discord" | string;

export interface ChannelProvider {
  provider: ChannelProviderId;
  display_name: string;
  enabled: boolean;
  configured: boolean;
  auth_mode: string;
  connection_status: string;
}

export interface ChannelProvidersResponse {
  enabled: boolean;
  providers: ChannelProvider[];
}

export interface ChannelConnection {
  id: string;
  provider: ChannelProviderId;
  status: string;
  external_account_id?: string | null;
  external_account_name?: string | null;
  workspace_id?: string | null;
  workspace_name?: string | null;
  scopes: string[];
  metadata: Record<string, unknown>;
}

export interface ChannelConnectionsResponse {
  connections: ChannelConnection[];
}

export interface ChannelConnectResponse {
  provider: ChannelProviderId;
  mode: string;
  url: string;
  expires_in: number;
}
