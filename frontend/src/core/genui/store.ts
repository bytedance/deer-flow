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
}

export interface InteractionState {
  status: "idle" | "loading" | "submitted" | "error" | "expired";
  error?: string;
  submittedAt?: number;
}

interface BlockStoreState {
  blocks: Map<string, UIBlock>;
  interactions: Map<string, InteractionState>;

  applyBlock: (block: UIBlock) => void;
  getChildBlocks: (parentId: string) => UIBlock[];
  setInteractionLoading: (callbackId: string) => void;
  setInteractionSuccess: (callbackId: string) => void;
  setInteractionError: (callbackId: string, error: string) => void;
  setInteractionExpired: (callbackId: string) => void;
  reset: () => void;
}

export const useBlockStore = create<BlockStoreState>((set, get) => ({
  blocks: new Map(),
  interactions: new Map(),

  applyBlock: (block: UIBlock) =>
    set((state) => {
      const blocks = new Map(state.blocks);
      const interactions = new Map(state.interactions);
      switch (block.action) {
        case "create":
          blocks.set(block.block_id, block);
          if (block.callback_id) {
            interactions.delete(block.callback_id);
          }
          break;
        case "update": {
          const existing = blocks.get(block.block_id);
          if (existing) {
            blocks.set(block.block_id, {
              ...existing,
              props: { ...existing.props, ...block.props },
            });
          } else {
            blocks.set(block.block_id, block);
          }
          break;
        }
        case "delete":
          blocks.delete(block.block_id);
          break;
      }
      return { blocks, interactions };
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

  reset: () => set({ blocks: new Map(), interactions: new Map() }),
}));
