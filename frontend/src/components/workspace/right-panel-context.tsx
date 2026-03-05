import { createContext, useContext, useState } from "react";

type RightPanelContextType = {
  open: boolean;
  setOpen: (open: boolean) => void;
};

const RightPanelContext = createContext<RightPanelContextType | null>(null);

export function RightPanelProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <RightPanelContext.Provider value={{ open, setOpen }}>
      {children}
    </RightPanelContext.Provider>
  );
}

export function useRightPanel(): RightPanelContextType {
  const ctx = useContext(RightPanelContext);
  // Fallback for use outside provider
  // eslint-disable-next-line @typescript-eslint/no-empty-function
  if (!ctx) return { open: false, setOpen: () => {} };
  return ctx;
}
