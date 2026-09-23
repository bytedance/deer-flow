/** Run the production importer in Chromium, including authenticated lazy chunks. */
import { spawn, type ChildProcess } from "node:child_process";
import { readFile } from "node:fs/promises";
import { createServer, type Server, type RequestListener } from "node:http";
import path from "node:path";

import { expect, test } from "@playwright/test";
import { ScriptTarget, ModuleKind, transpileModule } from "typescript";

type TestPlugin = {
  value: number;
  lazy: () => Promise<{ lazy: string }>;
  css: string;
  image: string;
};
declare global {
  interface Window {
    loadPlugin: (url: string) => Promise<{ default: TestPlugin }>;
    executions: number;
    releasePlugin: () => void;
    pluginResumed: Promise<void>;
    latePluginEffects: number;
  }
}

let frontend: Server;
let backend: Server;
let frontendURL: string;
let backendURL: string;
let gateway: ChildProcess;
let svgURL: string;
const requests: { path: string; cookie: string }[] = [];
async function listen(server: Server) {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("Missing port");
  return `http://127.0.0.1:${address.port}`;
}
test.beforeAll(async ({ request }) => {
  const source = await readFile("src/core/extensions/asset-module.ts", "utf8");
  const loader = transpileModule(source, {
    compilerOptions: { target: ScriptTarget.ES2022, module: ModuleKind.ESNext },
  }).outputText;
  const files: Record<string, [string, string]> = {
    "pending.mjs": [
      "text/javascript",
      `window.latePluginEffects = 0;
       let resumed;
       window.pluginResumed = new Promise(resolve => { resumed = resolve; });
       await new Promise(resolve => { window.releasePlugin = resolve; });
       window.latePluginEffects++;
       resumed();
       export default {};`,
    ],
    "index.mjs": [
      "text/javascript",
      `import { value } from './chunks/value.mjs';
      globalThis.executions = (globalThis.executions || 0) + 1;
      export default {value, lazy: () => import('./chunks/lazy.mjs'),
        css: new URL('./style.css', import.meta.url).href,
        image: new URL('./icon.svg', import.meta.url).href};`,
    ],
    "chunks/value.mjs": ["text/javascript", "export const value = 42;"],
    "chunks/lazy.mjs": [
      "text/javascript",
      'export const lazy = "authenticated lazy chunk";',
    ],
    "style.css": ["text/css", "body { --plugin-loaded: yes; }"],
    "icon.svg": [
      "image/svg+xml",
      '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"/>',
    ],
  };
  const handler: RequestListener = (req, res) => {
    if (req.url === "/") {
      res.setHeader("Content-Type", "text/html");
      res.end(
        '<!doctype html><script type="module">import { importAssetModule } from "/loader.mjs"; window.loadPlugin = importAssetModule;</script>',
      );
      return;
    }
    if (req.url === "/loader.mjs") {
      res.setHeader("Content-Type", "text/javascript");
      res.end(loader);
      return;
    }
    res.setHeader("Access-Control-Allow-Origin", frontendURL);
    res.setHeader("Access-Control-Allow-Credentials", "true");
    const path = req.url ?? "";
    requests.push({ path, cookie: req.headers.cookie ?? "" });
    if (!req.headers.cookie?.includes("plugin_session=synthetic")) {
      res.writeHead(401);
      res.end();
      return;
    }
    const file = files[path.replace(/^\/gateway\/assets\/[a-z]+\//, "")];
    if (!file) {
      res.writeHead(404);
      res.end();
      return;
    }
    res.setHeader("Content-Type", file[0]);
    res.setHeader("X-Content-Type-Options", "nosniff");
    res.setHeader("Content-Security-Policy", "sandbox");
    res.end(file[1]);
  };
  frontend = createServer(handler);
  frontendURL = await listen(frontend);
  backend = createServer(handler);
  backendURL = await listen(backend);
  const probe = createServer();
  const gatewayURL = await listen(probe);
  await new Promise<void>((resolve) => probe.close(() => resolve()));
  const backendDirectory = path.resolve("../backend");
  gateway = spawn(
    path.join(backendDirectory, ".venv/bin/python"),
    [
      "-m",
      "extension_test_fixtures.browser_asset_gateway",
      new URL(gatewayURL).port,
    ],
    { cwd: backendDirectory, stdio: "pipe" },
  );
  let diagnostics = "";
  gateway.stderr?.on("data", (chunk) => {
    diagnostics += String(chunk);
  });
  const headers = { cookie: "plugin_session=synthetic" };
  await expect
    .poll(
      async () => {
        if (gateway.exitCode !== null) throw new Error(diagnostics);
        return request
          .get(`${gatewayURL}/api/plugins`, { headers })
          .then((r) => r.status())
          .catch(() => 0);
      },
      { timeout: 20_000 },
    )
    .toBe(200);
  const response = await request.get(`${gatewayURL}/api/plugins`, { headers });
  const [plugin] = (await response.json()) as { entry: string }[];
  svgURL = `${gatewayURL}${plugin!.entry.replace("index.mjs", "active.svg")}`;
});
test.afterAll(async () => {
  if (gateway?.exitCode === null) {
    const exited = new Promise<void>((resolve) =>
      gateway.once("exit", () => resolve()),
    );
    gateway.kill("SIGTERM");
    await exited;
  }
  for (const server of [frontend, backend]) {
    server?.closeAllConnections();
    await new Promise<void>((resolve) => server?.close(() => resolve()));
  }
});

test("Gateway SVG renders as an image but direct navigation cannot execute its script", async ({
  page,
  context,
}) => {
  await context.addCookies([
    { name: "plugin_session", value: "synthetic", url: svgURL },
  ]);
  await page.goto(frontendURL);
  const width = await page.evaluate(async (url) => {
    const image = new Image();
    image.src = url;
    document.body.append(image);
    await image.decode();
    return image.naturalWidth;
  }, svgURL);
  expect(width).toBe(20);

  const response = await page.goto(svgURL);
  await expect(page.locator("svg")).toBeVisible();
  expect(await page.locator("svg").getAttribute("data-executed")).toBeNull();
  expect(response?.headers()["content-security-policy"]).toBe("sandbox");

  // Positive control: the same SVG really executes if its response loses the sandbox.
  await page.route(svgURL, async (route) => {
    const original = await route.fetch();
    const headers = original.headers();
    delete headers["content-security-policy"];
    await route.fulfill({ response: original, headers });
  });
  await page.goto(svgURL);
  await expect(page.locator("svg")).toHaveAttribute("data-executed", "yes");
});
for (const origin of ["same", "split"]) {
  test(`native ${origin}-origin graph loads static/lazy chunks, CSS and images with credentials`, async ({
    page,
    context,
  }) => {
    await context.addCookies([
      { name: "plugin_session", value: "synthetic", url: frontendURL },
    ]);
    requests.length = 0;
    await page.goto(frontendURL);
    await page.waitForFunction(() => typeof window.loadPlugin === "function");
    const result = await page.evaluate(
      async (url) => {
        const { default: plugin } = await window.loadPlugin(url);
        const lazy = await plugin.lazy();
        const stylesheet = document.createElement("link");
        stylesheet.rel = "stylesheet";
        stylesheet.crossOrigin = "use-credentials";
        stylesheet.href = plugin.css;
        const cssLoaded = new Promise<void>((resolve, reject) => {
          stylesheet.onload = () => resolve();
          stylesheet.onerror = reject;
        });
        document.head.append(stylesheet);
        const image = new Image();
        image.crossOrigin = "use-credentials";
        const imageLoaded = new Promise<void>((resolve, reject) => {
          image.onload = () => resolve();
          image.onerror = reject;
        });
        image.src = plugin.image;
        document.body.append(image);
        await Promise.all([cssLoaded, imageLoaded]);
        const again = await window.loadPlugin(url);
        return {
          value: plugin.value,
          lazy: lazy.lazy,
          css: getComputedStyle(document.body)
            .getPropertyValue("--plugin-loaded")
            .trim(),
          image: image.naturalWidth,
          sameInstance: again.default === plugin,
          executions: window.executions,
          scripts: document.querySelectorAll("script[src]").length,
        };
      },
      `${origin === "same" ? frontendURL : backendURL}/gateway/assets/${origin}/index.mjs`,
    );
    expect(result).toEqual({
      value: 42,
      lazy: "authenticated lazy chunk",
      css: "yes",
      image: 20,
      sameInstance: true,
      executions: 1,
      scripts: 0,
    });
    expect(
      requests.map((r) => r.path.split(`/assets/${origin}/`)[1]).sort(),
    ).toEqual([
      "chunks/lazy.mjs",
      "chunks/value.mjs",
      "icon.svg",
      "index.mjs",
      "style.css",
    ]);
    expect(
      requests.every((r) => r.cookie.includes("plugin_session=synthetic")),
    ).toBe(true);
  });
}
test("unauthenticated resource load rejects and removes the script", async ({
  page,
}) => {
  await page.goto(frontendURL);
  await page.waitForFunction(() => typeof window.loadPlugin === "function");
  const result = await page.evaluate(async (url) => {
    try {
      await window.loadPlugin(url);
      return "unexpected success";
    } catch (error) {
      return `${String(error)}; scripts=${document.querySelectorAll("script[src]").length}`;
    }
  }, `${backendURL}/gateway/assets/denied/index.mjs`);
  expect(result).toBe("Error: Plugin module unavailable; scripts=0");
});

test("timeout ends host waiting but cannot cancel late native module effects", async ({
  page,
  context,
}) => {
  test.setTimeout(40_000);
  await context.addCookies([
    { name: "plugin_session", value: "synthetic", url: frontendURL },
  ]);
  await page.goto(frontendURL);
  await page.waitForFunction(() => typeof window.loadPlugin === "function");
  const result = await page.evaluate(async (url) => {
    const attempt = window.loadPlugin(url).then(
      () => "unexpected success",
      (error: Error) => error.message,
    );
    const failure = await attempt;
    const scripts = document.querySelectorAll("script[src]").length;
    const effectsAtTimeout = window.latePluginEffects;
    // Release evaluation only after the deadline has settled the host result.
    window.releasePlugin();
    await window.pluginResumed;
    return {
      failure,
      scripts,
      effectsAtTimeout,
      effectsAfterResume: window.latePluginEffects,
      resultAfterResume: await attempt,
    };
  }, `${backendURL}/gateway/assets/pending/pending.mjs`);
  expect(result).toEqual({
    failure: "Plugin module timed out",
    scripts: 0,
    effectsAtTimeout: 0,
    effectsAfterResume: 1,
    resultAfterResume: "Plugin module timed out",
  });
});
