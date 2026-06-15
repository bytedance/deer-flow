import { useBlockStore } from "./store";
import type { UIBlock } from "./store";

const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30000;
const BACKOFF_MULTIPLIER = 2;

function getBackendBaseUrl(): string {
  if (typeof window !== "undefined") {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return ((window as any).__NEXT_PUBLIC_BACKEND_BASE_URL as string) ?? "";
  }
  return process.env.NEXT_PUBLIC_BACKEND_BASE_URL ?? "";
}

export class GenUISSEManager {
  private threadId: string;
  private backoffMs: number = INITIAL_BACKOFF_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private abortController: AbortController | null = null;
  private isConnected = false;
  private disposed = false;
  private visible = true;
  private pendingRecovery = false;

  constructor(threadId: string) {
    this.threadId = threadId;
  }

  setVisibility(isVisible: boolean): void {
    this.visible = isVisible;
    if (isVisible && this.pendingRecovery) {
      this.pendingRecovery = false;
      void this.recoverBlocks();
    }
    if (!isVisible && this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  async recoverBlocks(): Promise<void> {
    if (this.disposed || !this.visible) {
      this.pendingRecovery = true;
      return;
    }

    const baseUrl = getBackendBaseUrl();
    const url = `${baseUrl}/api/threads/${this.threadId}/ui-blocks`;

    this.abortController = new AbortController();

    try {
      const response = await fetch(url, { signal: this.abortController.signal });
      if (!response.ok || this.disposed) {
        return;
      }

      const blocks: UIBlock[] = await response.json();
      if (this.disposed) return;

      useBlockStore.getState().replaceAllBlocks(this.threadId, blocks);

      this.resetBackoff();
    } catch {
      if (!this.disposed) {
        this.scheduleReconnect();
      }
    }
  }

  scheduleReconnect(): void {
    if (this.reconnectTimer || !this.visible) {
      this.pendingRecovery = true;
      return;
    }

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      void this.recoverBlocks();
    }, this.backoffMs);

    this.backoffMs = Math.min(this.backoffMs * BACKOFF_MULTIPLIER, MAX_BACKOFF_MS);
  }

  private resetBackoff(): void {
    this.backoffMs = INITIAL_BACKOFF_MS;
    this.isConnected = true;
  }

  disconnect(): void {
    this.disposed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.abortController) {
      this.abortController.abort();
      this.abortController = null;
    }
    this.isConnected = false;
  }

  get connected(): boolean {
    return this.isConnected;
  }
}
