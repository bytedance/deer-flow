export interface CredentialField {
  key: string;
  label: string;
  inputType: "text" | "password";
  required: boolean;
  placeholder?: string;
  description?: string;
}

export interface ConnectorProvider {
  service: string;
  displayName: string;
  categories: (string | { name: string })[];
  authTypes: string[];
  auth?: {
    type: string;
    fields?: CredentialField[];
    label?: string;
    placeholder?: string;
    description?: string;
  }[];
  description?: string;
  homepageUrl?: string;
  oauthConfigured?: boolean;
  apiKeyConfigured?: boolean;
  customCredentialConfigured?: boolean | null;
}

export interface ConnectorAction {
  id: string;
  name: string;
  description: string;
  service: string;
  requiredScopes: string[];
  inputSchema: Record<string, unknown>;
}

export interface ConnectorConnection {
  id: string;
  service: string;
  /** v1 API: alias; legacy: connectionName */
  alias?: string;
  connectionName?: string;
  authType: string;
  isDefault?: boolean;
}

export interface ConnectorProvidersResponse {
  providers: ConnectorProvider[];
}

export interface ConnectorConnectionsResponse {
  connections: ConnectorConnection[];
}
