import { useCallback, useLayoutEffect, useState } from "react";

import {
  DEFAULT_LOCAL_SETTINGS,
  getLocalSettings,
  saveLocalSettings,
  type LocalSettings,
} from "./local";

export function useLocalSettings(): [
  LocalSettings,
  (
    key: keyof LocalSettings,
    value: Partial<LocalSettings[keyof LocalSettings]>,
  ) => void,
] {
  const [mounted, setMounted] = useState(false);
  const [state, setState] = useState<LocalSettings>(DEFAULT_LOCAL_SETTINGS);
  useLayoutEffect(() => {
    if (!mounted) {
      setState(getLocalSettings());
    }
    setMounted(true);
  }, [mounted]);
  const setter = useCallback(
    (
      key: keyof LocalSettings,
      value: Partial<LocalSettings[keyof LocalSettings]>,
    ) => {
      if (!mounted) return;
      setState((prev) => {
        const newState = {
          ...prev,
          [key]: {
            ...prev[key],
            ...value,
          },
        };
        saveLocalSettings(newState);
        return newState;
      });
    },
    [mounted],
  );
  return [state, setter];
}
