import { expect, rs, test } from "@rstest/core";

import { bindFrontendServices } from "@/core/extensions/services";

const { request } = rs.hoisted(() => ({ request: rs.fn() }));
rs.mock("@/core/api/fetcher", () => ({ fetch: request }));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));

const base = { conversationText: rs.fn(), showMessage: rs.fn() };
const entry = {
  namespace: "community.review",
  module: null,
  entry: null,
  title: "Review",
  description: "",
  settings: { enabled: true },
  backend_actions: ["read"],
};

test("installed page navigation binds namespace, registered surface and encoded thread context", () => {
  const navigate = rs.fn();
  const services = bindFrontendServices(base, entry, undefined, {
    pageIds: ["results"], navigate,
  });
  expect(typeof services.openPluginPage).toBe("function");
  services.openPluginPage!("results", "thread/&?x=1");
  expect(navigate).toHaveBeenCalledWith("/workspace/extensions/community.review/results?thread=thread%2F%26%3Fx%3D1");
  services.openPluginPage!("results");
  expect(navigate).toHaveBeenLastCalledWith("/workspace/extensions/community.review/results");
});

test("external and undeclared targets cannot escape the installed page set", () => {
  const navigate = rs.fn();
  const services = bindFrontendServices(base, entry, undefined, { pageIds: ["results"], navigate });
  for (const id of ["other", "https://example.com", "../../login", "", "__proto__"]) {
    expect(() => services.openPluginPage!(id, "thread")).toThrow("not declared");
  }
  expect(navigate).not.toHaveBeenCalled();
});

test("older hosts without page navigation do not gain an arbitrary URL helper", () => {
  expect(bindFrontendServices(base, entry).openPluginPage).toBeUndefined();
});

test("invalid or empty thread context fails before navigation", () => {
  const navigate = rs.fn();
  const services = bindFrontendServices(base, entry, undefined, { pageIds: ["results"], navigate });
  for (const thread of ["", "t".repeat(129)]) {
    expect(() => services.openPluginPage!("results", thread)).toThrow("Invalid conversation");
  }
  expect(navigate).not.toHaveBeenCalled();
});

test("disposed conversation actions cannot navigate through a retained helper", () => {
  const abort = new AbortController();
  const navigate = rs.fn();
  const services = bindFrontendServices(base, entry, abort.signal, { pageIds: ["results"], navigate });
  abort.abort();
  expect(() => services.openPluginPage!("results", "thread")).toThrow();
  expect(navigate).not.toHaveBeenCalled();
});

test("selection request cancellation and page lifetime cancellation both reach fetch", async () => {
  request.mockResolvedValue({ ok: true, json: async () => ({ result: "report" }) });
  const page = new AbortController();
  const selection = new AbortController();
  const services = bindFrontendServices(base, entry, page.signal);
  expect(await services.callBackend("read", {}, { signal: selection.signal })).toEqual({ result: "report" });
  const combined = request.mock.calls.at(-1)![1]!.signal as AbortSignal;
  expect(combined.aborted).toBe(false);
  selection.abort();
  expect(combined.aborted).toBe(true);
  const next = new AbortController();
  await services.callBackend("read", {}, { signal: next.signal });
  const second = request.mock.calls.at(-1)![1]!.signal as AbortSignal;
  expect(second.aborted).toBe(false);
  page.abort();
  expect(second.aborted).toBe(true);
});

test("request-specific cancellation also works without a page signal", async () => {
  request.mockResolvedValue({ ok: true, json: async () => [] });
  const selection = new AbortController();
  await bindFrontendServices(base, entry).callBackend("read", {}, { signal: selection.signal });
  expect(request.mock.calls.at(-1)![1]!.signal).toBe(selection.signal);
});
