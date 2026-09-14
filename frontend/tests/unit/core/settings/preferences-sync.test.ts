import { describe, expect, it } from "@rstest/core";

import {
  PreferencesSync,
  type Preferences,
} from "@/core/settings/preferences-sync";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function setup(
  read: () => Promise<Preferences>,
  patch: (value: Preferences) => Promise<void>,
) {
  let visible: Preferences = {};
  let pending: Preferences = {};
  const sync = new PreferencesSync(
    {
      read,
      patch,
      apply: (value) => {
        visible = value;
      },
      savePending: (value) => {
        pending = value;
      },
    },
    {},
    {},
  );
  return { sync, visible: () => visible, pending: () => pending };
}

describe("account preference synchronization", () => {
  it("retries a failed bootstrap and preserves edits made while loading", async () => {
    let attempts = 0;
    const writes: Preferences[] = [];
    const state = setup(
      async () => {
        if (++attempts === 1) throw new Error("offline");
        return { mode: "pro", notification_enabled: true };
      },
      async (value) => {
        writes.push(value);
      },
    );
    await expect(state.sync.flush()).rejects.toThrow("offline");
    state.sync.edit({ notification_enabled: false });
    await state.sync.flush();
    expect(writes).toEqual([{ notification_enabled: false }]);
    expect(state.visible()).toEqual({
      mode: "pro",
      notification_enabled: false,
    });
    expect(state.pending()).toEqual({});
  });

  it("does not let an older acknowledgement erase a newer edit", async () => {
    const ack = deferred<void>();
    const writes: Preferences[] = [];
    const state = setup(
      async () => ({}),
      async (value) => {
        writes.push(value);
        if (writes.length === 1) await ack.promise;
      },
    );
    await state.sync.flush();
    state.sync.edit({ mode: "pro" });
    const flushing = state.sync.flush();
    await Promise.resolve();
    state.sync.edit({ mode: "flash" });
    ack.resolve();
    await flushing;
    expect(writes).toEqual([{ mode: "pro" }, { mode: "flash" }]);
    expect(state.visible().mode).toBe("flash");
    expect(state.pending()).toEqual({});
  });

  it("ignores a late read after stopping an account", async () => {
    const read = deferred<Preferences>();
    const state = setup(
      () => read.promise,
      async () => undefined,
    );
    const loading = state.sync.flush();
    state.sync.stop();
    read.resolve({ model_name: "alice-only" });
    await loading;
    expect(state.visible()).toEqual({});
  });
});
