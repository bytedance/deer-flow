import { fetchGateway } from "@/core/api";

export interface GreetingResponse {
  greeting: string;
  suggestions: string[];
  language: string;
  alert_count?: number;
}

export async function fetchGreeting(threadId: string): Promise<GreetingResponse> {
  const response = await fetchGateway(`/api/threads/${encodeURIComponent(threadId)}/greeting`);
  if (!response.ok) {
    throw new Error(`Greeting fetch failed: ${response.status}`);
  }
  return response.json() as Promise<GreetingResponse>;
}
