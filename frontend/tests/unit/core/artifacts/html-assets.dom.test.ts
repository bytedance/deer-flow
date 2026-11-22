import { afterEach, expect, rs, test } from "@rstest/core";

import { prepareHtmlPreview } from "@/core/artifacts/html-assets";

const url =
  "https://app.example/api/threads/chat/artifacts/mnt/user-data/outputs/report.html";
const request = rs.spyOn(globalThis, "fetch");

afterEach(() => {
  request.mockReset();
});

test("preserves missing and legacy doctypes and comments outside the HTML element", async () => {
  for (const declaration of [
    "",
    "<!doctype html>",
    '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">',
    '<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">',
  ]) {
    const content = `<!--before-->${declaration}<html><body><h1>Report</h1></body></html><!--after-->`;
    const result = await prepareHtmlPreview(content, url);
    const expected = new DOMParser().parseFromString(content, "text/html");
    const actual = new DOMParser().parseFromString(result.content, "text/html");
    expect(actual.doctype?.name).toBe(expected.doctype?.name);
    expect(actual.doctype?.publicId).toBe(expected.doctype?.publicId);
    expect(actual.doctype?.systemId).toBe(expected.doctype?.systemId);
    expect(result.content).toContain("<!--before-->");
    expect(result.content).toContain("<!--after-->");
    expect(actual.querySelector("base")?.getAttribute("href")).toBe(
      url.replace("report.html", ""),
    );
  }
});

test("rewrites URLs inside SVG style elements and inline style attributes", async () => {
  request.mockImplementation(async () => new Response("image"));
  // happy-dom's HTML parser drops SVG children; create the namespace nodes
  // directly. The real parser is also exercised by the browser regression.
  const fixture = document.implementation.createHTMLDocument("");
  const svg = fixture.createElementNS("http://www.w3.org/2000/svg", "svg");
  const style = fixture.createElementNS("http://www.w3.org/2000/svg", "style");
  style.textContent = ".chart{fill:url(chart.svg#paint)}";
  const rect = fixture.createElementNS("http://www.w3.org/2000/svg", "rect");
  rect.setAttribute("style", "filter:url(filters.svg#blur)");
  svg.append(style, rect);
  fixture.body.append(svg);
  const parse = rs
    .spyOn(DOMParser.prototype, "parseFromString")
    .mockReturnValueOnce(fixture);
  const result = await prepareHtmlPreview(
    '<svg xmlns="http://www.w3.org/2000/svg"><style>.chart{fill:url(chart.svg#paint)}</style><rect class="chart" style="filter:url(filters.svg#blur)"/></svg>',
    url,
  );
  parse.mockRestore();
  expect(
    request.mock.calls.map(([input]) =>
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url,
    ),
  ).toEqual([
    url.replace("report.html", "chart.svg"),
    url.replace("report.html", "filters.svg"),
  ]);
  expect(style.textContent).toContain("data:");
  expect(rect.getAttribute("style")).toContain("data:");
  expect(result.content).toContain("#paint");
  expect(result.content).toContain("#blur");
});

test("authenticates images, scripts and nested CSS assets in the parent", async () => {
  request.mockImplementation(async (input) => {
    const pathname = new URL(
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url,
    ).pathname;
    if (pathname.endsWith("main.css"))
      return new Response(
        '@import "nested.css" screen; .hero{background:url("chart%2520.png")}',
      );
    if (pathname.endsWith("nested.css"))
      return new Response(".icon{background:url(../uploads/icon.png)}");
    return new Response(
      pathname.endsWith("app.js") ? "window.loaded=true" : "image",
    );
  });
  const result = await prepareHtmlPreview(
    '<link rel="stylesheet" href="main.css"><script src="app.js"></script><img src="chart%2520.png">',
    url,
  );
  expect(result.failedResources).toBe(0);
  expect(
    request.mock.calls.map(([input]) =>
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url,
    ),
  ).toEqual([
    url.replace("report.html", "main.css"),
    url.replace("report.html", "nested.css"),
    url.replace("outputs/report.html", "uploads/icon.png"),
    url.replace("report.html", "chart%2520.png"),
    url.replace("report.html", "app.js"),
  ]);
  expect(result.content).not.toContain('src="chart%2520.png"');
  const document = new DOMParser().parseFromString(result.content, "text/html");
  const css = atob(
    document.querySelector("link")!.getAttribute("href")!.split(",")[1]!,
  );
  expect(css).toContain("data:text/css");
  expect(
    request.mock.calls.every(([, init]) => init?.redirect === "error"),
  ).toBe(true);
});

test("never fetches another thread, external origin, non-artifact route or encoded separators", async () => {
  const result = await prepareHtmlPreview(
    `<img src="https://evil.example/image"><img src="/api/threads/other/artifacts/mnt/a.png"><img src="/api/memory"><img src="..%2fsecret.png"><img src="%5csecret.png"><img src="data:image/png;base64,AA">`,
    url,
  );
  expect(request).not.toHaveBeenCalled();
  expect(result.content).toContain("https://evil.example/image");
});

test("bounds cycles and failed resources without losing the HTML", async () => {
  request.mockImplementation(async (input) => {
    if (
      (typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url
      ).endsWith("a.css")
    )
      return new Response('@import "b.css";');
    if (
      (typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url
      ).endsWith("b.css")
    )
      return new Response('@import "a.css";');
    return new Response("missing", { status: 404 });
  });
  const result = await prepareHtmlPreview(
    '<h1>Report</h1><link rel="stylesheet" href="a.css"><img src="missing.png">',
    url,
  );
  expect(request).toHaveBeenCalledTimes(3);
  expect(result.failedResources).toBe(2);
  expect(result.content).toContain("Report");
  expect(result.content).not.toContain('src="missing.png"');
});

test("rewrites inline CSS and ignores commented URL text", async () => {
  request.mockResolvedValue(new Response("image"));
  const result = await prepareHtmlPreview(
    '<style>/*url(no.png)*/ .x{background:url("chart.png")}</style><div style="background:url(chart.png)"></div>',
    url,
  );
  expect(request).toHaveBeenCalledTimes(1);
  expect(result.content).toContain("/*url(no.png)*/");
  expect(result.content).toContain("data:");
});

test("leaves public demos and previews without a resource URL on their existing path", async () => {
  const content = '<img src="chart.png">';
  for (const value of [
    undefined,
    "https://app.example/demo/threads/chat/report.html",
  ]) {
    const result = await prepareHtmlPreview(content, value);
    expect(result.content).toContain(content);
    expect(request).not.toHaveBeenCalled();
  }
});

test("preserves external bases and escaped external CSS references", async () => {
  const result = await prepareHtmlPreview(
    '<base href="https://cdn.example/"><img src="image.png"><style>.x{background:url(https://cdn.example/a\\)b.png)}</style>',
    url,
  );
  expect(request).not.toHaveBeenCalled();
  expect(result.content).toContain('src="image.png"');
  expect(result.content).toContain("a\\)b.png");
});

test("supports responsive pictures, SVG fragments and CSS escaped filenames", async () => {
  request.mockImplementation(async () => new Response("image"));
  const result = await prepareHtmlPreview(
    '<picture><source srcset="one.png 1x, two.png 2x"><img srcset="data:image/png;base64,AA 1x, one.png 2x" src="icons.svg#chart"></picture><style>.x{background:url("chart\\20 image.png")}</style>',
    url,
  );
  expect(
    request.mock.calls.map(([input]) =>
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url,
    ),
  ).toEqual([
    url.replace("report.html", "one.png"),
    url.replace("report.html", "two.png"),
    url.replace("report.html", "icons.svg"),
    url.replace("report.html", "chart%20image.png"),
  ]);
  expect(result.content).toContain("data:image/png;base64,AA 1x");
  expect(result.content).toContain("#chart");
  expect(result.failedResources).toBe(0);
});

test("caps distinct resources and CSS import depth", async () => {
  request.mockImplementation(async () => new Response("image"));
  const result = await prepareHtmlPreview(
    Array.from({ length: 40 }, (_, i) => `<img src="${i}.png">`).join(""),
    url,
  );
  expect(request).toHaveBeenCalledTimes(32);
  expect(result.failedResources).toBe(8);
  request.mockClear();
  request.mockImplementation(async (input) => {
    const name = new URL(
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url,
    ).pathname
      .split("/")
      .pop()!;
    return new Response(`@import "${Number.parseInt(name) + 1}.css";`);
  });
  const nested = await prepareHtmlPreview(
    '<link rel="stylesheet" href="0.css">',
    url,
  );
  expect(request).toHaveBeenCalledTimes(9);
  expect(nested.failedResources).toBe(1);
});

test("caps streamed resource bytes and the aggregate budget", async () => {
  request.mockImplementation(
    async () => new Response(new Uint8Array(4 * 1024 * 1024 + 1)),
  );
  const oversized = await prepareHtmlPreview('<img src="huge.png">', url);
  expect(oversized.failedResources).toBe(1);
  expect(oversized.content).toContain('src="data:,"');
  request.mockClear();
  request.mockImplementation(
    async () => new Response(new Uint8Array(4 * 1024 * 1024)),
  );
  const aggregate = await prepareHtmlPreview(
    Array.from({ length: 5 }, (_, i) => `<img src="${i}.png">`).join(""),
    url,
  );
  expect(aggregate.failedResources).toBe(1);
  expect(request).toHaveBeenCalledTimes(4);
});

test("bounds repeated data URLs and preserves out-of-route CSS resolution", async () => {
  request.mockImplementation(
    async () => new Response(new Uint8Array(4 * 1024 * 1024)),
  );
  const repeated = await prepareHtmlPreview(
    Array.from({ length: 8 }, () => '<img src="chart.png">').join(""),
    url,
  );
  expect(request).toHaveBeenCalledTimes(1);
  expect(repeated.failedResources).toBeGreaterThan(0);
  expect(repeated.content.length).toBeLessThan(24 * 1024 * 1024);
  request.mockClear();
  request.mockResolvedValue(
    new Response(".x{background:url(/public/chart.png)}"),
  );
  const css = await prepareHtmlPreview(
    '<link rel="stylesheet" href="style.css">',
    url,
  );
  const document = new DOMParser().parseFromString(css.content, "text/html");
  const stylesheet = atob(
    document.querySelector("link")!.getAttribute("href")!.split(",")[1]!,
  );
  expect(stylesheet).toContain("https://app.example/public/chart.png");
  expect(request).toHaveBeenCalledTimes(1);
});

test("quotes absolute CSS URLs that replace escaped unquoted references", async () => {
  request.mockResolvedValue(
    new Response(".chart{background:url(//cdn.example/chart\\(1\\).png)}"),
  );
  const result = await prepareHtmlPreview(
    '<link rel="stylesheet" href="style.css">',
    url,
  );
  const document = new DOMParser().parseFromString(result.content, "text/html");
  const stylesheet = atob(
    document.querySelector("link")!.getAttribute("href")!.split(",")[1]!,
  );
  expect(stylesheet).toContain('url("https://cdn.example/chart(1).png")');
  expect(result.failedResources).toBe(0);
});

test("aborts late responses before exposing prepared HTML", async () => {
  const controller = new AbortController();
  request.mockImplementation(async (input) => {
    if (
      (typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url
      ).endsWith("late.png")
    )
      controller.abort();
    return new Response("image");
  });
  await expect(
    prepareHtmlPreview(
      '<img src="first.png"><img src="late.png">',
      url,
      controller.signal,
    ),
  ).rejects.toThrow();
});

test("validates original integrity before rewriting resources", async () => {
  request.mockImplementation(async () => new Response("body"));
  const result = await prepareHtmlPreview(
    '<link rel="stylesheet" href="style.css" integrity="sha256-original"><script src="app.js" integrity="sha256-script"></script><link rel="stylesheet" href="https://cdn.example/style.css" integrity="sha256-external">',
    url,
  );
  expect(request.mock.calls.map(([, init]) => init?.integrity)).toEqual([
    "sha256-original",
    "sha256-script",
  ]);
  expect(result.content).not.toContain("sha256-original");
  expect(result.content).not.toContain("sha256-script");
  expect(result.content).toContain("sha256-external");
});

test("never reuses an unverified resource for a distinct integrity constraint", async () => {
  request.mockImplementation(async (_input, init) => {
    if (init?.integrity === "sha256-wrong")
      throw new TypeError("Integrity mismatch");
    return new Response("image");
  });
  const result = await prepareHtmlPreview(
    '<img src="chart.png"><img src="chart.png" integrity="sha256-valid"><img src="chart.png" integrity="sha256-wrong">',
    url,
  );
  expect(request.mock.calls.map(([, init]) => init?.integrity)).toEqual([
    undefined,
    "sha256-valid",
    "sha256-wrong",
  ]);
  expect(result.failedResources).toBe(1);
  expect(result.content).toContain('src="data:,"');
});

test("returns a partial preview when the preparation deadline expires", async () => {
  rs.useFakeTimers();
  try {
    request.mockImplementation(
      (_input, init) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener(
            "abort",
            () => reject(new DOMException("Aborted", "AbortError")),
            { once: true },
          );
        }),
    );
    const pending = prepareHtmlPreview(
      '<h1>Report</h1><img src="slow.png"><img src="next.png">',
      url,
    );
    await rs.advanceTimersByTimeAsync(10_000);
    const result = await pending;
    expect(result.failedResources).toBe(2);
    expect(request).toHaveBeenCalledTimes(1);
    expect(result.content).toContain("Report");
  } finally {
    rs.useRealTimers();
  }
});
