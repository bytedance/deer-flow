import type { TokenUsage } from "./usage";

export interface TokenDebugStep {
  id: string;
  messageId: string;
  label: string;
  secondaryLabels: string[];
  usage: TokenUsage | null;
  sharedAttribution: boolean;
}
