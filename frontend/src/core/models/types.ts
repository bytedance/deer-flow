export interface Model {
  id?: string;
  name: string;
  model: string;
  display_name?: string | null;
  description?: string | null;
  provider?: string | null;
  provider_label?: string | null;
  provider_url?: string | null;
  modalities?: string[] | null;
  supports_thinking?: boolean;
  supports_reasoning_effort?: boolean;
}
