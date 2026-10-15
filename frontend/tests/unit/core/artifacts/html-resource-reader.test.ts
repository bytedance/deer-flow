import { afterEach, expect, it, rs } from "@rstest/core";

import { createWorkspaceRESTClient } from "@/core/api/fetcher";
import { createHTMLArtifactResourceReader } from "@/core/artifacts/html-resource-reader";
import { urlOfArtifact } from "@/core/artifacts/utils";

const P = "11111111-1111-1111-1111-111111111111";
const T = "22222222-2222-2222-2222-222222222222";
type Seen = {
  url: URL;
  init: RequestInit | undefined;
  workspace: string | null;
};
function transport() {
  const seen: Seen[] = [];
  rs.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = new URL(
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url,
      "http://localhost:2026",
    );
    const workspace = new Headers(init?.headers).get("X-Deerflow-Workspace");
    seen.push({ url, init, workspace });
    if (url.pathname.endsWith("main.css"))
      return new Response("body{background:url(../img/chart.png)}", {
        headers: { "Content-Type": "text/css;charset=utf-8" },
      });
    if (url.pathname.endsWith("chart.png"))
      return new Response(new Uint8Array([0, 255, 1, 4]), {
        headers: {
          "Content-Type": "image/png",
          "Set-Cookie": "fixture-private",
          Authorization: "fixture-private",
        },
      });
    return new Response(`data:${workspace}`, {
      headers: { "Content-Type": "text/csv;charset=utf-8" },
    });
  });
  return seen;
}
function lifetime(workspaceId: string) {
  const controller = new AbortController();
  const scope = {
    actorUserId: "alice",
    workspaceId,
    signal: controller.signal,
  };
  return { controller, scope, rest: createWorkspaceRESTClient(scope) };
}
function source() {
  return urlOfArtifact({
    threadId: "thread-1",
    filepath: "/mnt/user-data/outputs/reports/report.html",
    workspaceId: T,
  });
}
afterEach(() => {
  rs.restoreAllMocks();
});
it("reads report stylesheet, nested image and uploaded data bytes with the captured native workspace client", async () => {
  const seen = transport();
  for (const workspace of [P, T]) {
    const owner = lifetime(workspace);
    const reader = createHTMLArtifactResourceReader({
      sourceURL: source(),
      lifetime: owner,
    });
    const css = await reader.read(
      `./css/main.css?download=true&workspace_id=${T}&workspace_id=${P}#theme`,
    );
    expect(new TextDecoder().decode(css.bytes)).toBe(
      "body{background:url(../img/chart.png)}",
    );
    expect(css.contentType).toBe("text/css;charset=utf-8");
    expect(new URL(css.url).searchParams.getAll("workspace_id")).toEqual([
      workspace,
    ]);
    expect(new URL(css.url).searchParams.get("download")).toBe("true");
    expect(new URL(css.url).hash).toBe("#theme");
    const image = await reader.read("../img/chart.png", { baseURL: css.url });
    expect(new Uint8Array(image.bytes)).toEqual(new Uint8Array([0, 255, 1, 4]));
    expect(image.contentType).toBe("image/png");
    expect(image.status).toBe(200);
    expect(new URL(image.url).pathname).toBe(
      "/api/threads/thread-1/artifacts/mnt/user-data/outputs/reports/img/chart.png",
    );
    expect(JSON.stringify(image)).not.toContain("fixture-private");
    const data = await reader.read("/mnt/user-data/uploads/input%2520data.csv");
    expect(new URL(data.url).pathname).toBe(
      "/api/threads/thread-1/artifacts/mnt/user-data/uploads/input%2520data.csv",
    );
    expect(new TextDecoder().decode(data.bytes)).toBe(`data:${workspace}`);
    const literalSeparator = await reader.read(
      "/mnt/user-data/uploads/input%252fdata.csv",
    );
    expect(new URL(literalSeparator.url).pathname).toBe(
      "/api/threads/thread-1/artifacts/mnt/user-data/uploads/input%252fdata.csv",
    );
    reader.dispose();
    expect(owner.scope.signal.aborted).toBe(false);
  }
  expect(seen).toHaveLength(8);
  for (const request of seen) {
    expect(request.url.searchParams.get("workspace_id")).toBe(
      request.workspace,
    );
    expect(request.url.hash).toBe("");
    expect(request.init?.method).toBe("GET");
    expect(request.init?.credentials).toBe("include");
    expect(request.init?.redirect).toBe("error");
    expect(request.init?.cache).toBe("no-store");
  }
});

it("captures one native report source and refuses external, API, foreign-thread and escaped byte targets", async () => {
  const seen = transport();
  const owner = lifetime(P);
  const options = { sourceURL: source(), lifetime: owner };
  const reader = createHTMLArtifactResourceReader(options);
  const foreign = urlOfArtifact({
    threadId: "thread-2",
    filepath: "/mnt/user-data/outputs/data.csv",
    workspaceId: T,
  });
  options.sourceURL = foreign;
  owner.scope.workspaceId = T;
  owner.rest = createWorkspaceRESTClient(owner.scope);
  const original = await reader.read("./snapshot.csv");
  expect(new TextDecoder().decode(original.bytes)).toBe(`data:${P}`);
  expect(seen[0]?.workspace).toBe(P);
  expect(seen[0]?.url.pathname).toBe(
    "/api/threads/thread-1/artifacts/mnt/user-data/outputs/reports/snapshot.csv",
  );
  expect(seen[0]?.url.searchParams.getAll("workspace_id")).toEqual([P]);
  const origin = new URL(reader.sourceURL).origin;
  const credentials = new URL(reader.sourceURL);
  credentials.username = "fixture";
  for (const reference of [
    "https://example.test/data.csv",
    `${origin}/api/v1/auth/me`,
    foreign,
    "../../../../../../../../outside.csv",
    credentials.href,
    "./%252f..%252f..%252f..%252f..%252f..%252f..%252f..%252fapi/v1/auth/me",
    "#chart",
  ]) {
    expect(reader.resolve(reference)).toBeUndefined();
    await expect(reader.read(reference)).rejects.toBeInstanceOf(TypeError);
  }
  await expect(
    reader.read("./data.csv", { baseURL: new URL(foreign, origin).href }),
  ).rejects.toBeInstanceOf(TypeError);
  expect(() =>
    createHTMLArtifactResourceReader({
      sourceURL: `${origin}/api/v1/auth/me`,
      lifetime: owner,
    }),
  ).toThrow();
  expect(seen).toHaveLength(1);
  const denied = new Response("fixture-private-server-detail", { status: 404 });
  rs.spyOn(globalThis, "fetch").mockResolvedValue(denied);
  await expect(reader.read("./missing.csv")).rejects.toMatchObject({
    status: 404,
    message: "Failed to load HTML artifact resource",
  });
  reader.dispose();
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
it("rejects held byte decoders after report, request or workspace retirement without cancelling unrelated reports", async () => {
  for (const retired of ["report", "request", "workspace"] as const) {
    const owner = lifetime(P);
    const reader = createHTMLArtifactResourceReader({
      sourceURL: source(),
      lifetime: owner,
    });
    const entered = deferred<void>(),
      release = deferred<void>();
    const response = new Response(new Uint8Array([1]));
    rs.spyOn(response, "arrayBuffer").mockImplementation(async () => {
      entered.resolve();
      await release.promise;
      return new Uint8Array([1]).buffer;
    });
    const wire = rs.spyOn(globalThis, "fetch").mockResolvedValue(response);
    const request = new AbortController();
    const pending = reader.read("./held.csv", { signal: request.signal });
    const rejected = expect(pending).rejects.toMatchObject({
      name: "AbortError",
    });
    await entered.promise;
    if (retired === "report") reader.dispose();
    else if (retired === "request") request.abort();
    else owner.controller.abort();
    release.resolve();
    await rejected;
    expect(owner.scope.signal.aborted).toBe(retired === "workspace");
    wire.mockResolvedValue(new Response(new Uint8Array([7])));
    if (retired !== "request") {
      const calls = wire.mock.calls.length;
      await expect(reader.read("./after.csv")).rejects.toMatchObject({
        name: "AbortError",
      });
      expect(wire.mock.calls).toHaveLength(calls);
    }
    if (retired !== "workspace") {
      const current =
        retired === "report"
          ? createHTMLArtifactResourceReader({
              sourceURL: source(),
              lifetime: owner,
            })
          : reader;
      expect(new Uint8Array((await current.read("./fresh.csv")).bytes)).toEqual(
        new Uint8Array([7]),
      );
      current.dispose();
    }
    reader.dispose();
  }
});
