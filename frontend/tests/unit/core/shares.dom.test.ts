import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement } from "react";

import { ShareMarkdown } from "@/components/shares/share-markdown";
import { forkShare, readShare, shareArtifactURL } from "@/core/shares/api";
import { resolveShareArtifact, sharedLink } from "@/core/shares/links";

const artifact = {
  path: "charts/a b.svg",
  mime_type: "image/svg+xml",
  size: 10,
  sha256: "hash",
};
const token = "x".repeat(43);
afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

describe("share boundaries", () => {
  it("keeps image URL suffixes while refusing external and private images", async () => {
    render(
      createElement(ShareMarkdown, {
        token,
        artifacts: [artifact],
        content:
          "![detail](sandbox:/mnt/user-data/outputs/charts/a%20b.svg?v=2&download=summary#detail) ![tracking](https://tracker.example/pixel.svg) ![private](/api/threads/private/artifacts/a.svg) ![missing](missing.svg)",
      }),
    );
    expect((await screen.findByAltText("detail")).getAttribute("src")).toBe(
      shareArtifactURL(token, artifact.path) + "?v=2#detail",
    );
    expect(screen.queryAllByRole("img")).toHaveLength(1);
  });

  it.each([
    ["?download=summary#detail", "#detail"],
    ["?download=1", ""],
    [
      "?v=a%20b&%64ownload=1&download=false&v=%2f#detail?download=1",
      "?v=a%20b&v=%2f#detail?download=1",
    ],
    ["?label=download%3D1#detail", "?label=download%3D1#detail"],
  ])(
    "keeps copied link queries separate from download controls (%s)",
    (query, suffix) => {
      expect(sharedLink(`charts/a%20b.svg${query}`, token, [artifact])).toBe(
        shareArtifactURL(token, artifact.path) + suffix,
      );
    },
  );

  it("resolves URL suffixes separately from encoded filename punctuation", () => {
    const punctuated = { ...artifact, path: "charts/a#b?.svg" };
    for (const suffix of ["#page=3", "?v=2", "?v=2#section"]) {
      const href = `charts/a%20b.svg${suffix}`;
      expect(resolveShareArtifact(href, [artifact])).toEqual(artifact);
      expect(sharedLink(href, token, [artifact])).toBe(
        shareArtifactURL(token, artifact.path) + suffix,
      );
    }
    expect(
      resolveShareArtifact("charts/a%23b%3F.svg#section", [punctuated]),
    ).toEqual(punctuated);
    expect(
      resolveShareArtifact("../../private.svg#section", [artifact]),
    ).toBeUndefined();
    expect(
      resolveShareArtifact("/api/threads/private/artifacts/a.svg#section", [
        artifact,
      ]),
    ).toBeUndefined();
  });

  it("only resolves copied outputs, including relative markdown references", () => {
    expect(
      resolveShareArtifact("sandbox:/mnt/user-data/outputs/charts/a%20b.svg", [
        artifact,
      ]),
    ).toEqual(artifact);
    expect(
      resolveShareArtifact("../charts/a b.svg", [artifact], "reports/"),
    ).toEqual(artifact);
    for (const path of [
      "/api/threads/private/artifacts/file",
      "/mnt/user-data/uploads/private",
      "../../charts/a b.svg",
      "javascript:alert(1)",
      "https://tracker.example/a.svg",
      "%zz",
    ]) {
      expect(resolveShareArtifact(path, [artifact])).toBeUndefined();
    }
    expect(shareArtifactURL(token, artifact.path)).toContain(
      `/shares/${token}/artifacts/charts/a%20b.svg`,
    );
    expect(
      sharedLink(
        `${window.location.origin}/workspace/chats/private`,
        token,
        [],
      ),
    ).toBeUndefined();
    expect(sharedLink("https://example.org/report", token, [])).toBe(
      "https://example.org/report",
    );
    expect(sharedLink("https://secret@example.org", token, [])).toBeUndefined();
  });

  it("reads anonymously without forwarding session credentials or caching", async () => {
    const signal = new AbortController().signal;
    const fetch = rs
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(new Response("{}", { status: 404 }));
    await expect(readShare(token, signal)).rejects.toMatchObject({
      status: 404,
    });
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({
      credentials: "omit",
      cache: "no-store",
      referrerPolicy: "no-referrer",
      signal,
    });
  });

  it("authenticates before sending an idempotent, CSRF-protected fork", async () => {
    document.cookie = "csrf_token=fixture; path=/";
    const fetch = rs
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response("{}"))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ thread_id: "copy" })),
      );
    await expect(
      forkShare(token, "request-1", new AbortController().signal),
    ).resolves.toEqual({ thread_id: "copy" });
    expect(fetch.mock.calls[0]?.[0]).toContain("/api/v1/auth/me");
    expect(fetch.mock.calls[1]?.[0]).toContain(`/shares/${token}/fork`);
    expect(fetch.mock.calls[1]?.[1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({ request_id: "request-1" }),
    });
    expect(
      new Headers(fetch.mock.calls[1]?.[1]?.headers).get("x-csrf-token"),
    ).toBe("fixture");
  });
});
