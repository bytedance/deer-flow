import { fetch as fetchWithCsrf } from "@/core/api/fetcher";

import { uploadPendingScreenshots } from "./chart-screenshots";
import { useBlockStore } from "./store";

const MAX_RETRIES = 2;
const RETRY_DELAY_MS = 1000;

interface InteractionResponse {
  success: boolean;
  message: string;
  callback_id: string;
}

function getBackendBaseUrl(): string {
  if (typeof window !== "undefined") {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return ((window as any).__NEXT_PUBLIC_BACKEND_BASE_URL as string) ?? "";
  }
  return process.env.NEXT_PUBLIC_BACKEND_BASE_URL ?? "";
}

async function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export interface SubmitInteractionOptions {
  onSuccess?: (callbackId: string, payload: Record<string, unknown>) => void;
}

export async function submitInteraction(
  threadId: string,
  blockId: string | undefined,
  callbackId: string,
  payload: Record<string, unknown>,
  options?: SubmitInteractionOptions,
): Promise<InteractionResponse> {
  const store = useBlockStore.getState();
  store.setInteractionLoading(blockId ?? callbackId);

  const baseUrl = getBackendBaseUrl();
  const url = `${baseUrl}/api/threads/${threadId}/ui-interaction`;

  const chartImages = await uploadPendingScreenshots(threadId);
  const enrichedPayload = chartImages.length > 0
    ? { ...payload, chart_images: chartImages }
    : payload;

  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const response = await fetchWithCsrf(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ callback_id: callbackId, payload: enrichedPayload }),
      });

      if (response.status === 410) {
        store.setInteractionExpired(blockId ?? callbackId);
        return { success: false, message: "Interaction expired", callback_id: callbackId };
      }

      if (!response.ok) {
        const detail = await response.text();
        // 404 "Unknown callback" is a race condition: the backend may still be
        // registering the callback from the render_ui tool call that created
        // this block. Retry with a longer delay to give the server time to
        // finish the registration before giving up.
        const isUnknownCallback =
          response.status === 404 && detail.includes("Unknown callback");
        if (isUnknownCallback && attempt < MAX_RETRIES) {
          lastError = new Error(`HTTP ${response.status}: ${detail}`);
          await delay(RETRY_DELAY_MS * 3 * (attempt + 1));
          continue;
        }
        throw new Error(`HTTP ${response.status}: ${detail}`);
      }

      const data: InteractionResponse = await response.json();
      store.setInteractionSuccess(blockId ?? callbackId);
      // Skip event dispatch for idempotent submissions — prevents duplicate
      // human messages from being sent to the thread.
      if (data.message !== "Already submitted (idempotent)") {
        options?.onSuccess?.(callbackId, payload);
        window.dispatchEvent(
          new CustomEvent("genui:interaction-submitted", {
            detail: { threadId, blockId, callbackId, payload },
          }),
        );
      }
      return data;
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));
      if (attempt < MAX_RETRIES) {
        await delay(RETRY_DELAY_MS * (attempt + 1));
      }
    }
  }

  const errorMessage = lastError?.message ?? "Unknown error";
  store.setInteractionError(blockId ?? callbackId, errorMessage);
  return { success: false, message: errorMessage, callback_id: callbackId };
}
