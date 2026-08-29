import { afterEach, expect, test, rs } from "@rstest/core";

afterEach(() => {
  rs.unstubAllGlobals();
});

function stubFetch(responses: Response[]) {
  const fetchMock = rs.fn(async () => {
    const response = responses.shift();
    if (!response) throw new Error("unexpected extra fetch call");
    return response;
  });
  rs.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

test("listPats returns the caller's token summaries", async () => {
  const fetchMock = stubFetch([
    new Response(
      JSON.stringify([
        {
          id: "pat-1",
          name: "ci-runner",
          scopes: ["runs:create", "threads:read"],
          expires_at: null,
          last_used_at: null,
          created_at: "2026-08-27T10:30:00+00:00",
          revoked_at: null,
        },
      ]),
      { status: 200 },
    ),
  ]);

  const { listPats } = await import("@/core/pats/api");
  const pats = await listPats();

  expect(pats).toHaveLength(1);
  expect(pats[0]?.name).toBe("ci-runner");
  expect(fetchMock).toHaveBeenCalledWith(
    expect.stringContaining("/api/v1/auth/pats"),
    expect.objectContaining({ credentials: "include" }),
  );
});

test("createPat posts the request body with CSRF-eligible method", async () => {
  const fetchMock = stubFetch([
    new Response(
      JSON.stringify({
        id: "pat-2",
        name: "ci",
        scopes: ["threads:read"],
        expires_at: "2026-11-25T10:30:00+00:00",
        last_used_at: null,
        created_at: "2026-08-27T10:30:00+00:00",
        revoked_at: null,
        token: "dfp_testtoken",
      }),
      { status: 201 },
    ),
  ]);

  const { createPat } = await import("@/core/pats/api");
  const created = await createPat({
    name: "ci",
    scopes: ["threads:read"],
    expires_in_days: 90,
  });

  expect(created.token).toBe("dfp_testtoken");
  const [url, init] = fetchMock.mock.calls[0] as unknown as [
    string,
    RequestInit,
  ];
  expect(url).toContain("/api/v1/auth/pats");
  expect(init.method).toBe("POST");
  const body = typeof init.body === "string" ? init.body : "";
  expect(JSON.parse(body)).toEqual({
    name: "ci",
    scopes: ["threads:read"],
    expires_in_days: 90,
  });
});

test("createPat surfaces pydantic 422 array detail as a joined message", async () => {
  stubFetch([
    new Response(
      JSON.stringify({
        detail: [
          {
            type: "value_error",
            loc: ["body", "name"],
            msg: "Value error, PAT name must contain at least one non-whitespace character",
          },
        ],
      }),
      { status: 422 },
    ),
  ]);

  const { createPat } = await import("@/core/pats/api");

  await expect(
    createPat({
      name: " ",
      scopes: ["threads:read"],
      expires_in_days: null,
    }),
  ).rejects.toThrow(/non-whitespace/);
});

test("listPats maps a 503 memory-backend response to PatStoreUnavailableError", async () => {
  stubFetch([
    new Response(
      JSON.stringify({
        detail: "Personal access tokens require a configured database",
      }),
      { status: 503 },
    ),
  ]);

  const { listPats, PatStoreUnavailableError } =
    await import("@/core/pats/api");

  await expect(listPats()).rejects.toBeInstanceOf(PatStoreUnavailableError);
});

test("createPat maps a 503 memory-backend response to PatStoreUnavailableError", async () => {
  stubFetch([
    new Response(JSON.stringify({ detail: "no store" }), { status: 503 }),
  ]);

  const { createPat, PatStoreUnavailableError } =
    await import("@/core/pats/api");

  await expect(
    createPat({ name: "ci", scopes: ["threads:read"], expires_in_days: null }),
  ).rejects.toBeInstanceOf(PatStoreUnavailableError);
});

test("revokePat maps a 503 memory-backend response to PatStoreUnavailableError", async () => {
  stubFetch([
    new Response(JSON.stringify({ detail: "no store" }), { status: 503 }),
  ]);

  const { revokePat, PatStoreUnavailableError } =
    await import("@/core/pats/api");

  await expect(revokePat("pat-1")).rejects.toBeInstanceOf(
    PatStoreUnavailableError,
  );
});

test("revokePat issues DELETE against the encoded token id", async () => {
  const fetchMock = stubFetch([
    new Response(JSON.stringify({ message: "Token revoked" }), {
      status: 200,
    }),
  ]);

  const { revokePat } = await import("@/core/pats/api");
  await revokePat("pat/1");

  const [url, init] = fetchMock.mock.calls[0] as unknown as [
    string,
    RequestInit,
  ];
  expect(url).toContain("/api/v1/auth/pats/pat%2F1");
  expect(init.method).toBe("DELETE");
});

test("revokePat surfaces a 404 not-found detail", async () => {
  stubFetch([
    new Response(JSON.stringify({ detail: "Token not found" }), {
      status: 404,
    }),
  ]);

  const { revokePat } = await import("@/core/pats/api");

  await expect(revokePat("missing")).rejects.toThrow("Token not found");
});
