"use client";

import { createContext, useCallback, useContext } from "react";

interface BlockPersistContextValue {
  saveContent: (blockId: string, content: string) => Promise<void>;
}

const BlockPersistContext = createContext<BlockPersistContextValue | null>(null);

export function BlockPersistProvider({
  children,
  saveContent,
}: {
  children: React.ReactNode;
  saveContent: (blockId: string, content: string) => Promise<void>;
}) {
  const save = useCallback(
    async (blockId: string, content: string) => {
      await saveContent(blockId, content);
    },
    [saveContent],
  );

  return (
    <BlockPersistContext.Provider value={{ saveContent: save }}>
      {children}
    </BlockPersistContext.Provider>
  );
}

export function useBlockPersist(): BlockPersistContextValue | null {
  return useContext(BlockPersistContext);
}
