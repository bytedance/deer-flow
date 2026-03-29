import { useCallback, useLayoutEffect, useState } from "react";

import {
  DEFAULT_LOCAL_SETTINGS,
  getLocalSettings,
  saveLocalSettings,
  type LocalSettings,
} from "./local";

export function useLocalSettings(threadId?: string): [
  LocalSettings,
  (
    key: keyof LocalSettings,
    value: Partial<LocalSettings[keyof LocalSettings]>,
  ) => void,
] {
  const [state, setState] = useState<LocalSettings>(DEFAULT_LOCAL_SETTINGS);

  const [mounted, setMounted] = useState(false);
  useLayoutEffect(() => {
    setState(getLocalSettings(threadId));
    setMounted(true);
  }, [threadId]);

  const setter = useCallback(
    (
      key: keyof LocalSettings,
      value: Partial<LocalSettings[keyof LocalSettings]>,
    ) => {
      if (!mounted) return;
      setState((prev) => {
        const newState: LocalSettings = {
          ...prev,
          [key]: {
            ...prev[key],
            ...value,
          },
        };
        saveLocalSettings(newState, threadId);
        return newState;
      });
    },
    [mounted, threadId],
  );
  return [state, setter];
}
