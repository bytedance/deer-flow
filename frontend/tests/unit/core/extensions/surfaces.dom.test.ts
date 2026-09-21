import { expect, rs, test } from "@rstest/core";

import { mountSurface } from "@/core/extensions/surfaces";

test("surface cleanup aborts outstanding work and rejects late backend calls", async () => {
  const container = document.createElement("div");
  const dispose = rs.fn();
  const backend = rs.fn(async () => ({}));
  let callLater: (
    name: string,
    payload: Record<string, unknown>,
  ) => Promise<unknown> = rs.fn();
  let signal: AbortSignal | undefined;
  const cleanup = mountSurface(
    container,
    {
      id: "picker",
      slot: "page",
      title: "Picker",
      mount(root, context) {
        signal = context.signal;
        callLater = context.callBackend;
        root.textContent = "PLUGIN UI";
        return { dispose };
      },
    },
    {
      namespace: "community.example",
      locale: "en",
      settings: {},
      threadId: "a",
      callBackend: backend,
    },
    rs.fn(),
  );
  expect(container.shadowRoot?.textContent).toBe("PLUGIN UI");
  await callLater("search", {});
  cleanup();
  cleanup();
  await expect(callLater("search", {})).rejects.toThrow();
  expect(backend).toHaveBeenCalledTimes(1);
  expect(signal?.aborted).toBe(true);
  expect(dispose).toHaveBeenCalledTimes(1);
  expect(container.shadowRoot?.textContent).toBe("");
});

test("a failed mount is isolated and cannot leave its partial UI behind", () => {
  const error = rs.fn();
  const container = document.createElement("div");
  mountSurface(
    container,
    {
      id: "bad",
      slot: "page",
      title: "Broken",
      mount(root) {
        root.textContent = "partial";
        throw new Error("broken");
      },
    },
    {
      namespace: "community.example",
      locale: "en",
      settings: {},
      callBackend: rs.fn(),
    },
    error,
  );
  expect(error).toHaveBeenCalledTimes(1);
  expect(container.shadowRoot?.textContent).toBe("");
});
