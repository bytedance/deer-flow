import { afterEach, expect, rs, test } from "@rstest/core";

import { LOCAL_SETTINGS_KEY } from "@/core/settings/local";
import {
  getBaseSettingsSnapshot,
  updateLocalSettings,
} from "@/core/settings/store";

function createStorage() {
  const data = new Map<string, string>();
  return {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => {
      data.set(key, value);
    },
    removeItem: (key: string) => {
      data.delete(key);
    },
    clear: () => {
      data.clear();
    },
  };
}

const layout = {
  version: 1 as const,
  primary: ["search", "agents"],
  more: ["usage"],
};

afterEach(() => {
  rs.unstubAllGlobals();
});

test("persists a customized sidebar layout in the local settings blob", () => {
  const storage = createStorage();
  rs.stubGlobal("window", {
    localStorage: storage,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  });

  updateLocalSettings("navLayout", layout);

  expect(getBaseSettingsSnapshot().navLayout).toEqual(layout);

  const stored = JSON.parse(storage.getItem(LOCAL_SETTINGS_KEY) ?? "{}") as {
    navLayout?: unknown;
  };
  expect(stored.navLayout).toEqual(layout);
});
