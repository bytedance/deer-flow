import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import { createServer, type Server } from "node:http";
import { createRequire } from "node:module";
import path from "node:path";
import { promisify } from "node:util";

import {
  expect,
  test as base,
  type Page,
  type TestInfo,
} from "@playwright/test";

import { officeFixtures, officePackage } from "./utils/office-preview";

interface Zip {
  file(name: string, value: string): Zip;
  generateAsync(options: {
    type: "nodebuffer";
    compression: "STORE";
  }): Promise<Buffer>;
}
const JSZip = createRequire(
  path.resolve("../examples/deerflow-extension-office-preview/package.json"),
)("jszip") as { loadAsync(bytes: Buffer): Promise<Zip> };
let browserPid = 0;
const test = base.extend({
  browser: [
    async ({ playwright }, use) => {
      const server = await playwright.chromium.launchServer({
        executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
        args: ["--enable-precise-memory-info"],
      });
      browserPid = server.process().pid ?? 0;
      const browser = await playwright.chromium.connect(server.wsEndpoint());
      try {
        await use(browser);
      } finally {
        await browser.close();
        await server.close();
      }
    },
    { scope: "worker" },
  ],
});
test.describe.configure({ mode: "default" });
test.skip(
  process.platform !== "linux",
  "Process-tree RSS measurements use Linux ps.",
);
const samplingTimers = new Set<ReturnType<typeof setInterval>>();
test.afterEach(() => {
  for (const timer of samplingTimers) clearInterval(timer);
  samplingTimers.clear();
});
let server: Server, origin: string, entry: string, documentBytes: Buffer;
let workerMode = "normal";
test.beforeAll(async () => {
  const manifest = JSON.parse(
    await readFile(path.join(officePackage, "ui_manifest.json"), "utf8"),
  ) as { entry: string; files: string[] };
  entry = `/assets/${manifest.entry}`;
  server = createServer((request, response) => {
    void (async () => {
      const filename = new URL(request.url!, "http://localhost").pathname;
      if (filename === "/") {
        response.setHeader("Content-Type", "text/html");
        response.end(
          '<html><body style="height:800px"><button id="cancel">Cancel</button><div id="preview" style="height:750px"></div></body></html>',
        );
      } else if (filename === "/document") response.end(documentBytes);
      else if (
        filename.startsWith("/assets/") &&
        manifest.files.includes(filename.slice(8))
      ) {
        response.setHeader("Content-Type", "text/javascript");
        response.setHeader("Content-Security-Policy", "sandbox"); // Real Gateway asset policy.
        response.end(
          filename.endsWith("/office-worker.mjs") && workerMode === "stalled"
            ? "while(true) {}"
            : (filename.endsWith("/office-worker.mjs") &&
              workerMode.startsWith("phase-")
                ? `(() => { const post = self.postMessage.bind(self); self.postMessage = (data, ...args) => { post(data, ...args); if (data.phase === ${JSON.stringify(workerMode.slice(6))}) while (true) {} }; })();\n`
                : "") +
                (await readFile(
                  path.join(officePackage, filename.slice(8)),
                  "utf8",
                )),
        );
      } else {
        response.statusCode = 404;
        response.end();
      }
    })().catch(() => {
      response.statusCode = 500;
      response.end();
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  if (!address || typeof address === "string")
    throw new Error("No test server address");
  origin = `http://127.0.0.1:${address.port}`;
});
test.afterAll(async () => {
  await new Promise<void>((resolve) => server?.close(() => resolve()));
});
test.beforeEach(() => {
  workerMode = "normal";
});

async function mount(page: Page, filename: string, shortenDeadline = false) {
  await page.goto(origin);
  await page.evaluate(
    async ({ entry, filename, shortenDeadline }) => {
      const root = document.getElementById("preview")!;
      const probe = {
        terminated: 0,
        created: 0,
        maxGap: 0,
        longTasks: [] as number[],
        phases: [] as string[],
      };
      Object.assign(window, { officeProbe: probe });
      let last = performance.now();
      setInterval(() => {
        const now = performance.now();
        probe.maxGap = Math.max(probe.maxGap, now - last);
        last = now;
      }, 16);
      new PerformanceObserver((list) =>
        probe.longTasks.push(...list.getEntries().map((task) => task.duration)),
      ).observe({ entryTypes: ["longtask"] });
      const NativeWorker = window.Worker;
      window.Worker = class extends NativeWorker {
        constructor(url: string | URL, options?: WorkerOptions) {
          super(url, options);
          probe.created++;
          this.addEventListener("message", ({ data }) => {
            if (typeof data.phase === "string") probe.phases.push(data.phase);
          });
        }
        terminate() {
          probe.terminated++;
          super.terminate();
        }
      };
      if (shortenDeadline) {
        const original = window.setTimeout.bind(window);
        window.setTimeout = ((
          handler: TimerHandler,
          delay?: number,
          ...args: unknown[]
        ) =>
          original(
            handler,
            delay === 15000 ? 1000 : delay,
            ...args,
          )) as typeof window.setTimeout;
      }
      const contribution = (await import(entry)).default;
      const mounted = contribution.artifactPreviews[0].mount(root, {
        filename,
        locale: "en-US",
        signal: new AbortController().signal,
        readFile: async () => (await fetch("/document")).arrayBuffer(),
        onError: () => {
          root.textContent = "Preview failed safely";
          root.dataset.failed = "true";
        },
      });
      document.getElementById("cancel")!.onclick = () => {
        mounted.dispose();
        root.dataset.cancelled = "true";
      };
    },
    { entry, filename, shortenDeadline },
  );
}

type Probe = {
  maxGap: number;
  longTasks: number[];
  terminated: number;
  created: number;
  phases: string[];
};
// Browser process-tree RSS includes worker isolates, native parsing/image memory and UI.
async function measure(page: Page, info: TestInfo) {
  const cdp = await page.context().newCDPSession(page);
  let baseline = 0,
    peakRss = 0,
    peakUiHeap = 0,
    sampling = false;
  const sample = async () => {
    if (sampling) return;
    sampling = true;
    try {
      const { stdout } = await promisify(execFile)("ps", [
        "-eo",
        "pid=,ppid=,rss=",
      ]);
      const processes = stdout
        .trim()
        .split("\n")
        .map((line) => line.trim().split(/\s+/).map(Number));
      const descendants = new Set([browserPid]);
      let previous = -1;
      while (previous !== descendants.size) {
        previous = descendants.size;
        for (const [pid, parent] of processes)
          if (descendants.has(parent!)) descendants.add(pid!);
      }
      const rss = processes.reduce(
        (sum, [pid, , size]) =>
          sum + (descendants.has(pid!) ? size! * 1024 : 0),
        0,
      );
      baseline ||= rss;
      peakRss = Math.max(peakRss, rss);
      peakUiHeap = Math.max(
        peakUiHeap,
        (await cdp.send("Runtime.getHeapUsage")).usedSize,
      );
    } finally {
      sampling = false;
    }
  };
  await sample();
  const pending = new Set<Promise<void>>();
  const timer = setInterval(() => {
    const promise = sample()
      .catch(() => undefined)
      .finally(() => pending.delete(promise));
    pending.add(promise);
  }, 100);
  samplingTimers.add(timer);
  return async () => {
    clearInterval(timer);
    samplingTimers.delete(timer);
    await Promise.all(pending);
    await sample();
    const probe = await page.evaluate(
      () => (window as unknown as { officeProbe: Probe }).officeProbe,
    );
    const measurements = {
      peakBrowserRssBytes: peakRss,
      browserRssIncreaseBytes: peakRss - baseline,
      peakUiHeapBytes: peakUiHeap,
      ...probe,
    };
    await info.attach("office-resource-measurements", {
      body: JSON.stringify(measurements, null, 2),
      contentType: "application/json",
    });
    console.log(info.title, measurements);
    expect(probe.created).toBe(1);
    expect(probe.terminated).toBe(1);
    expect(probe.maxGap).toBeLessThan(1000);
    expect(peakRss).toBeGreaterThan(0);
    expect(peakRss - baseline).toBeLessThan(384 * 1024 * 1024);
  };
}
for (const [kind, name, xml] of [
  ["xlsx", "navigation.xlsx", "xl/worksheets/sheet1.xml"],
  ["docx", "navigation.docx", "word/document.xml"],
  ["pptx", "project-review.pptx", "ppt/slides/slide1.xml"],
]) {
  test(`${kind} rejects complexity within the original archive limits without freezing`, async ({
    page,
  }, info) => {
    const zip = await JSZip.loadAsync(
      await readFile(path.join(officeFixtures, name!)),
    );
    zip.file(xml!, "<root>" + "<n/>".repeat(100001) + "</root>");
    documentBytes = await zip.generateAsync({
      type: "nodebuffer",
      compression: "STORE",
    });
    expect(documentBytes.length).toBeLessThan(25 * 1024 * 1024);
    const done = await measure(page, info);
    await mount(page, name!);
    await expect(page.locator("#preview")).toHaveAttribute(
      "data-failed",
      "true",
    );
    await done();
  });
}
test("deadline terminates a synchronous parser loop while the UI remains responsive", async ({
  page,
}, info) => {
  workerMode = "stalled";
  documentBytes = await readFile(path.join(officeFixtures, "navigation.xlsx"));
  const done = await measure(page, info);
  await mount(page, "navigation.xlsx", true);
  await expect(page.locator("#preview")).toHaveAttribute("data-failed", "true");
  await done();
});
test("disposing an active preview terminates parsing without a stale error", async ({
  page,
}, info) => {
  workerMode = "stalled";
  documentBytes = await readFile(path.join(officeFixtures, "navigation.docx"));
  const done = await measure(page, info);
  await mount(page, "navigation.docx");
  await expect
    .poll(() =>
      page.evaluate(
        () => (window as unknown as { officeProbe: Probe }).officeProbe.created,
      ),
    )
    .toBe(1);
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.locator("#preview")).toHaveAttribute(
    "data-cancelled",
    "true",
  );
  await expect(page.locator("#preview")).toBeEmpty();
  await done();
});
for (const [name, selector] of [
  ["navigation.xlsx", "table"],
  ["navigation.docx", "section.docx"],
  ["project-review.pptx", "iframe.slide"],
]) {
  test(`${name} renders through the packaged worker and Gateway asset policy`, async ({
    page,
  }, info) => {
    documentBytes = await readFile(path.join(officeFixtures, name!));
    const done = await measure(page, info);
    await mount(page, name!);
    await expect(page.locator(`#preview ${selector}`).first()).toBeVisible({
      timeout: 20000,
    });
    await done();
  });
}

test("a dense workbook within the new budgets renders in interruptible batches", async ({
  page,
}, info) => {
  const zip = await JSZip.loadAsync(
    await readFile(path.join(officeFixtures, "navigation.xlsx")),
  );
  const column = (value: number): string =>
    value <= 26
      ? String.fromCharCode(64 + value)
      : `A${String.fromCharCode(64 + value - 26)}`;
  const rows = Array.from(
    { length: 400 },
    (_, r) =>
      `<row r="${r + 1}">${Array.from({ length: 40 }, (_, c) => `<c r="${column(c + 1)}${r + 1}" t="inlineStr"><is><t>Cell ${r + 1},${c + 1}</t></is></c>`).join("")}</row>`,
  ).join("");
  zip.file(
    "xl/worksheets/sheet1.xml",
    `<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>${rows}</sheetData></worksheet>`,
  );
  documentBytes = await zip.generateAsync({
    type: "nodebuffer",
    compression: "STORE",
  });
  const done = await measure(page, info);
  await mount(page, "dense.xlsx");
  await expect(page.locator("#preview td")).toHaveCount(16000, {
    timeout: 20000,
  });
  await done();
});

test("a long Word document within the new budgets stays responsive in DOM rendering", async ({
  page,
}, info) => {
  const zip = await JSZip.loadAsync(
    await readFile(path.join(officeFixtures, "navigation.docx")),
  );
  zip.file(
    "word/document.xml",
    `<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>${"<w:p><w:r><w:t>Bounded layout paragraph.</w:t></w:r></w:p>".repeat(1000)}<w:sectPr/></w:body></w:document>`,
  );
  documentBytes = await zip.generateAsync({
    type: "nodebuffer",
    compression: "STORE",
  });
  const done = await measure(page, info);
  await mount(page, "long.docx");
  await expect(page.locator("#preview section.docx p")).toHaveCount(1000, {
    timeout: 20000,
  });
  await page
    .getByRole("searchbox", { name: "Find in file", exact: true })
    .fill("a");
  await expect(page.getByRole("status", { name: "Search matches" })).toHaveText(
    "1 / 2000",
  );
  await expect(page.locator("#preview mark[data-office-match]")).toHaveCount(
    2000,
  );
  await done();
});

for (const [name, selector] of [
  ["navigation.docx", "section.docx"],
  ["project-review.pptx", "iframe.slide"],
]) {
  test(`${name} renders without invoking an XML parser on the main thread`, async ({
    page,
  }) => {
    documentBytes = await readFile(path.join(officeFixtures, name!));
    await page.addInitScript(() => {
      const NativeDOMParser = window.DOMParser;
      window.DOMParser = class extends NativeDOMParser {
        parseFromString(text: string, type: DOMParserSupportedType) {
          if (type !== "text/html")
            throw new Error("Office XML must be parsed in its worker");
          return super.parseFromString(text, type);
        }
      };
    });
    await mount(page, name!);
    await expect(page.locator(`#preview ${selector}`).first()).toBeVisible({
      timeout: 20000,
    });
  });
}

for (const [kind, name] of [
  ["docx", "navigation.docx"],
  ["pptx", "project-review.pptx"],
]) {
  for (const action of ["cancel", "deadline"]) {
    test(`${kind} ${action} terminates a worker stalled in document conversion`, async ({
      page,
    }, info) => {
      workerMode = `phase-${kind}`;
      documentBytes = await readFile(path.join(officeFixtures, name!));
      const done = await measure(page, info);
      await mount(page, name!, action === "deadline");
      await expect
        .poll(() =>
          page.evaluate(
            () =>
              (window as unknown as { officeProbe: Probe }).officeProbe.phases,
          ),
        )
        .toContain(kind);
      if (action === "cancel") {
        await page.getByRole("button", { name: "Cancel", exact: true }).click();
        await expect(page.locator("#preview")).toBeEmpty();
      } else
        await expect(page.locator("#preview")).toHaveAttribute(
          "data-failed",
          "true",
        );
      await done();
    });
  }
}

test("worker Word models preserve inline images, headers and footers", async ({
  page,
}) => {
  documentBytes = await readFile(
    path.join(officeFixtures, "worker-resources.docx"),
  );
  await mount(page, "worker-resources.docx");
  await expect(
    page.getByText("Worker header text", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Worker footer text", { exact: true }),
  ).toBeVisible();
  const image = page.locator("#preview section.docx img");
  await expect(image).toHaveCount(1);
  await expect
    .poll(() =>
      image.evaluate((node) => (node as HTMLImageElement).naturalWidth),
    )
    .toBe(2);
  const url = await image.getAttribute("src");
  expect(url?.startsWith("blob:")).toBe(true);
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(
    await page.evaluate(async (url) => {
      try {
        await fetch(url!);
        return false;
      } catch {
        return true;
      }
    }, url),
  ).toBe(true);
});
