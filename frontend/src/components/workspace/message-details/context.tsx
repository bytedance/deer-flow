"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export interface MessageDetail {
  id: string;
  title: string;
  content: ReactNode;
  actions?: ReactNode;
}

interface MessageDetailsContextValue {
  open: boolean;
  selectedDetail: MessageDetail | null;
  select: (detail: MessageDetail, origin?: HTMLElement) => void;
  close: (options?: { restoreFocus?: boolean }) => void;
}

const MessageDetailsContext = createContext<MessageDetailsContextValue | null>(
  null,
);

export function MessageDetailsProvider({
  children,
  onSelect,
}: {
  children: ReactNode;
  onSelect?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [selectedDetail, setSelectedDetail] = useState<MessageDetail | null>(
    null,
  );
  const originRef = useRef<HTMLElement | undefined>(undefined);
  const restoreFocusRef = useRef(false);
  useEffect(() => {
    if (!open && restoreFocusRef.current) {
      restoreFocusRef.current = false;
      if (originRef.current?.isConnected) {
        originRef.current.focus({ preventScroll: true });
      }
    }
  }, [open]);
  const select = useCallback(
    (detail: MessageDetail, origin?: HTMLElement) => {
      originRef.current = origin;
      restoreFocusRef.current = false;
      onSelect?.();
      setSelectedDetail(detail);
      setOpen(true);
    },
    [onSelect],
  );
  const close = useCallback((options?: { restoreFocus?: boolean }) => {
    restoreFocusRef.current = options?.restoreFocus !== false;
    setOpen(false);
  }, []);
  const value = useMemo(
    () => ({ open, selectedDetail, select, close }),
    [open, selectedDetail, select, close],
  );
  return (
    <MessageDetailsContext.Provider value={value}>
      {children}
    </MessageDetailsContext.Provider>
  );
}

export function useMaybeMessageDetails() {
  return useContext(MessageDetailsContext);
}
