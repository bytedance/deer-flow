import { useCallback, useLayoutEffect, useState } from "react";

import {
  DEFAULT_LOCAL_SETTINGS,
  getLocalSettings,
  getThreadLocalSettings,
  saveLocalSettings,
  saveThreadLocalSettings,
  type LocalSettings,
} from "./local";

type LocalSettingsSetter = (
  key: keyof LocalSettings,
  value: Partial<LocalSettings[keyof LocalSettings]>,
) => void;

function useSettingsState(
  getSettings: () => LocalSettings,
  saveSettings: (settings: LocalSettings) => void,
): [LocalSettings, LocalSettingsSetter] {
  const [state, setState] = useState<LocalSettings>(DEFAULT_LOCAL_SETTINGS);

  const [mounted, setMounted] = useState(false);
  useLayoutEffect(() => {
    setState(getSettings());
    setMounted(true);
  }, [getSettings]);

  const setter = useCallback<LocalSettingsSetter>(
    (key, value) => {
      if (!mounted) return;
      setState((prev) => {
        const newState: LocalSettings = {
          ...prev,
          [key]: {
            ...prev[key],
            ...value,
          },
        };
        saveSettings(newState);
        return newState;
      });
    },
    [mounted, saveSettings],
  );

  return [state, setter];
}

export function useLocalSettings(): [LocalSettings, LocalSettingsSetter] {
  return useSettingsState(getLocalSettings, saveLocalSettings);
}

export function useThreadSettings(
  threadId: string,
): [LocalSettings, LocalSettingsSetter] {
  return useSettingsState(
    useCallback(() => getThreadLocalSettings(threadId), [threadId]),
    useCallback(
      (settings: LocalSettings) => saveThreadLocalSettings(threadId, settings),
      [threadId],
    ),
  );
}
