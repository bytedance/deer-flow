import { useBlockStore } from "./store";
import type { UIBlock } from "./store";

const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30000;
const BACKOFF_MULTIPLIER = 2;

const UI_BLOCK_PATTERN = /<!--ui_block:(.+?)-->/g;

function getBackendBaseUrl(): string {
  if (typeof window !== "undefined") {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return ((window as any).__NEXT_PUBLIC_BACKEND_BASE_URL as string) ?? "";
  }
  return process.env.NEXT_PUBLIC_BACKEND_BASE_URL ?? "";
}

/**
 * Extract UI blocks embedded in message content (frontend-side checkpoint recovery).
 * Mirrors the backend's extract_blocks_from_messages logic.
 */
export function extractBlocksFromMessages(messages: { type?: string; content?: unknown }[]): UIBlock[] {
  const blocks = new Map<string, UIBlock>();

  for (const msg of messages) {
    if (msg.type !== "tool") continue;
    const content = msg.content;
    if (!content || typeof content !== "string") continue;
    if (!content.includes("<!--ui_block:")) continue;

    UI_BLOCK_PATTERN.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = UI_BLOCK_PATTERN.exec(content)) !== null) {
      try {
        const block = JSON.parse(match[1]!) as UIBlock;
        if (!block.block_id) continue;

        const action = block.action ?? "create";
        if (action === "delete") {
          blocks.delete(block.block_id);
        } else if (action === "update") {
          const existing = blocks.get(block.block_id);
          if (existing) {
            blocks.set(block.block_id, {
              ...existing,
              props: { ...existing.props, ...block.props },
            });
          } else {
            blocks.set(block.block_id, block);
          }
        } else {
          blocks.set(block.block_id, block);
        }
      } catch {
        // skip malformed JSON
      }
    }
  }

  return Array.from(blocks.values());
}

/**
 * Recover blocks from messages and apply them to the store.
 * This is a frontend-side fallback that doesn't depend on the backend API.
 */
export function recoverBlocksFromMessages(messages: { type?: string; content?: unknown }[]): void {
  const blocks = extractBlocksFromMessages(messages);
  if (blocks.length === 0) return;

  const store = useBlockStore.getState();
  const existing = store.blocks;
  for (const block of blocks) {
    if (!existing.has(block.block_id)) {
      store.applyBlock({ ...block, action: "create" });
    }
  }
}

export class GenUISSEManager {
  private threadId: string;
  private backoffMs: number = INITIAL_BACKOFF_MS;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private abortController: AbortController | null = null;
  private isConnected = false;
  private disposed = false;

  constructor(threadId: string) {
    this.threadId = threadId;
  }

  async recoverBlocks(): Promise<void> {
    if (this.disposed) return;

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

      const store = useBlockStore.getState();

      for (const block of blocks) {
        store.applyBlock({
          ...block,
          action: "create",
        });
      }

      this.resetBackoff();
    } catch {
      if (!this.disposed) {
        this.scheduleReconnect();
      }
    }
  }

  scheduleReconnect(): void {
    if (this.reconnectTimer) {
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
