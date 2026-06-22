import { afterEach, expect, test, rs } from "@rstest/core";

import {
  clearReconnectRun,
  getAPIClient,
  isInactiveRunStreamError,
} from "@/core/api/api-client";

function makeSessionStorage() {
  const values = new Map<string, string>();
  return {
    getItem: rs.fn((key: string) => values.get(key) ?? null),
    removeItem: rs.fn((key: string) => {
      values.delete(key);
    }),
    setItem: rs.fn((key: string, value: string) => {
      values.set(key, value);
    }),
  };
}

afterEach(() => {
  rs.unstubAllGlobals();
});

test("identifies inactive run stream errors", () => {
  const error = Object.assign(
    new Error(
      'HTTP 409: {"detail":"Run run-1 is not active on this worker and cannot be streamed"}',
    ),
    { status: 409 },
  );

  expect(isInactiveRunStreamError(error)).toBe(true);
});

test("does not classify unrelated conflict errors as inactive streams", () => {
  const error = Object.assign(new Error("HTTP 409: run is still active"), {
    status: 409,
  });

  expect(isInactiveRunStreamError(error)).toBe(false);
});

test("clears matching reconnect metadata", () => {
  const sessionStorage = makeSessionStorage();
  sessionStorage.setItem("lg:stream:thread-1", "run-1");
  rs.stubGlobal("window", { sessionStorage });

  clearReconnectRun("thread-1", "run-1");

  expect(sessionStorage.removeItem).toHaveBeenCalledWith("lg:stream:thread-1");
});

test("keeps newer reconnect metadata", () => {
  const sessionStorage = makeSessionStorage();
  sessionStorage.setItem("lg:stream:thread-1", "newer-run");
  rs.stubGlobal("window", { sessionStorage });

  clearReconnectRun("thread-1", "stale-run");

  expect(sessionStorage.removeItem).not.toHaveBeenCalled();
});

test("ignores reconnect metadata storage access failures", () => {
  rs.stubGlobal("window", {
    get sessionStorage() {
      throw new DOMException("Blocked", "SecurityError");
    },
  });

  expect(() => clearReconnectRun("thread-1", "run-1")).not.toThrow();
});

test("clears stale reconnect metadata when join stream cannot be resumed", async () => {
  const sessionStorage = makeSessionStorage();
  sessionStorage.setItem("lg:stream:thread-1", "run-1");
  rs.stubGlobal("window", {
    location: { origin: "http://localhost:2026" },
    sessionStorage,
  });
  rs.stubGlobal(
    "fetch",
    rs.fn(async () => {
      return new Response(
        JSON.stringify({
          detail:
            "Run run-1 is not active on this worker and cannot be streamed",
        }),
        { status: 409 },
      );
    }),
  );

  await expect(
    getAPIClient(true).runs.joinStream("thread-1", "run-1").next(),
  ).resolves.toMatchObject({ done: true });

  expect(sessionStorage.removeItem).toHaveBeenCalledWith("lg:stream:thread-1");
});

test("rethrows unrelated streaming errors", async () => {
  const sessionStorage = makeSessionStorage();
  sessionStorage.setItem("lg:stream:thread-1", "run-1");
  rs.stubGlobal("window", {
    location: { origin: "http://localhost:2026" },
    sessionStorage,
  });
  rs.stubGlobal(
    "fetch",
    rs.fn(async () => {
      return new Response(JSON.stringify({ detail: "run is still active" }), {
        status: 409,
      });
    }),
  );

  await expect(
    getAPIClient(true).runs.joinStream("thread-1", "run-1").next(),
  ).rejects.toThrow("HTTP 409");

  expect(sessionStorage.removeItem).not.toHaveBeenCalled();
});
