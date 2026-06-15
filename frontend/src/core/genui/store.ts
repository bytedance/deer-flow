import { create } from "zustand";

export interface UIBlock {
  schema_version: string;
  type: "ui_block";
  action: "create" | "update" | "delete";
  block_id: string;
  component: string;
  props: Record<string, unknown>;
  interactive: boolean;
  callback_id?: string;
  callback_timeout_ms?: number;
  parent_id?: string;
  metadata?: Record<string, unknown>;
  sequence?: number;
  functional_interaction?: boolean;
  interaction_status?: "submitted" | "idle";
  thread_id?: string;
}

export interface InteractionState {
  status: "idle" | "loading" | "submitted" | "error" | "expired" | "readonly";
  error?: string;
  submittedAt?: number;
}

export function getInteractionKey(block: {
  block_id?: string;
  callback_id?: string;
}): string | undefined {
  return block.block_id ?? block.callback_id;
}

interface BlockStoreState {
  activeThreadId: string | null;
  blocks: Map<string, UIBlock>;
  interactions: Map<string, InteractionState>;

  setActiveThread: (threadId: string | null) => void;
  replaceAllBlocks: (threadId: string, newBlocks: UIBlock[]) => void;
  upsertBlock: (threadId: string, block: UIBlock) => void;
  updateBlockProps: (blockId: string, props: Record<string, unknown>) => void;
  getChildBlocks: (parentId: string) => UIBlock[];
  setInteractionLoading: (callbackId: string) => void;
  setInteractionSuccess: (callbackId: string) => void;
  setInteractionError: (callbackId: string, error: string) => void;
  setInteractionExpired: (callbackId: string) => void;
  reset: () => void;
}

export const useBlockStore = create<BlockStoreState>((set, get) => ({
  activeThreadId: null,
  blocks: new Map(),
  interactions: new Map(),

  setActiveThread: (threadId: string | null) =>
    set({ activeThreadId: threadId }),

  replaceAllBlocks: (threadId: string, newBlocks: UIBlock[]) =>
    set((state) => {
      const blocks = new Map<string, UIBlock>();
      // Preserve blocks from OTHER threads
      for (const [key, block] of state.blocks) {
        if (block.thread_id !== threadId) {
          blocks.set(key, block);
        }
      }
      // Add new blocks, tagged with the correct thread
      for (const block of newBlocks) {
        blocks.set(block.block_id, { ...block, thread_id: threadId });
      }

      const interactions = new Map(state.interactions);
      for (const [key] of state.interactions) {
        let found = false;
        for (const block of blocks.values()) {
          if (getInteractionKey(block) === key) {
            found = true;
            break;
          }
        }
        if (!found) {
          interactions.delete(key);
        }
      }

      return { blocks, interactions };
    }),

  upsertBlock: (threadId: string, block: UIBlock) =>
    set((state) => {
      const blocks = new Map(state.blocks);
      blocks.set(block.block_id, { ...block, thread_id: threadId });
      return { blocks };
    }),

  updateBlockProps: (blockId: string, props: Record<string, unknown>) =>
    set((state) => {
      const existing = state.blocks.get(blockId);
      if (!existing) {
        return state;
      }
      const blocks = new Map(state.blocks);
      blocks.set(blockId, { ...existing, props: { ...existing.props, ...props } });
      return { blocks };
    }),

  getChildBlocks: (parentId: string) => {
    const { blocks } = get();
    const children: UIBlock[] = [];
    for (const block of blocks.values()) {
      if (block.parent_id === parentId) {
        children.push(block);
      }
    }
    return children;
  },

  setInteractionLoading: (callbackId: string) =>
    set((state) => {
      const interactions = new Map(state.interactions);
      interactions.set(callbackId, { status: "loading" });
      return { interactions };
    }),

  setInteractionSuccess: (callbackId: string) =>
    set((state) => {
      const interactions = new Map(state.interactions);
      interactions.set(callbackId, {
        status: "submitted",
        submittedAt: Date.now(),
      });
      return { interactions };
    }),

  setInteractionError: (callbackId: string, error: string) =>
    set((state) => {
      const interactions = new Map(state.interactions);
      interactions.set(callbackId, { status: "error", error });
      return { interactions };
    }),

  setInteractionExpired: (callbackId: string) =>
    set((state) => {
      const interactions = new Map(state.interactions);
      interactions.set(callbackId, { status: "expired" });
      return { interactions };
    }),

  reset: () => set({ activeThreadId: null, blocks: new Map(), interactions: new Map() }),
}));
