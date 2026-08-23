import { expect, test, type Page, type Route } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

type Dataset = {
  id: string;
  name: string;
  description: string;
  document_count: number;
  chunk_count: number;
  done_count?: number;
};

type Document = {
  id: string;
  name: string;
  run: string;
  size: number;
  chunk_count: number;
  update_time: number;
};

function fulfillJson(route: Route, body: unknown) {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function mockKnowledgeAPI(
  page: Page,
  initial: { datasets: Dataset[]; documents?: Document[] },
) {
  let datasets = [...initial.datasets];
  let documents = [...(initial.documents ?? [])];

  void page.route("**/api/knowledge/events", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      headers: { "Cache-Control": "no-cache" },
      body: [
        "event: dataset_parsing_progress",
        'data: {"dataset_id":"dataset-1","unstart_count":0,"running_count":1,"cancel_count":0,"done_count":1,"fail_count":0}',
        "",
        "",
      ].join("\n"),
    }),
  );

  void page.route("**/api/knowledge/datasets**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const documentMatch =
      /\/api\/knowledge\/datasets\/([^/]+)\/documents$/.exec(url.pathname);
    const parseMatch = /\/api\/knowledge\/datasets\/([^/]+)\/parse$/.exec(
      url.pathname,
    );
    const datasetMatch = /\/api\/knowledge\/datasets\/([^/]+)$/.exec(
      url.pathname,
    );

    if (documentMatch && method === "GET") {
      return fulfillJson(route, {
        code: 0,
        data: { docs: documents, total: documents.length },
      });
    }
    if (documentMatch && method === "POST") {
      const uploaded = {
        id: "document-uploaded",
        name: "uploaded.txt",
        run: "UNSTART",
        size: 7,
        chunk_count: 0,
        update_time: 1_786_000_000_000,
      };
      documents = [...documents, uploaded];
      datasets = datasets.map((dataset) =>
        dataset.id === decodeURIComponent(documentMatch[1] ?? "")
          ? { ...dataset, document_count: documents.length }
          : dataset,
      );
      return fulfillJson(route, { code: 0, data: [uploaded] });
    }
    if (documentMatch && method === "DELETE") {
      const body = request.postDataJSON() as { ids: string[] };
      documents = documents.filter(
        (document) => !body.ids.includes(document.id),
      );
      return fulfillJson(route, { code: 0, data: true });
    }
    if (parseMatch && method === "POST") {
      const body = request.postDataJSON() as { document_ids: string[] };
      documents = documents.map((document) =>
        body.document_ids.includes(document.id)
          ? { ...document, run: "RUNNING" }
          : document,
      );
      return fulfillJson(route, { code: 0, data: true });
    }
    if (datasetMatch && method === "DELETE") {
      const id = decodeURIComponent(datasetMatch[1] ?? "");
      datasets = datasets.filter((dataset) => dataset.id !== id);
      return fulfillJson(route, { code: 0, data: true });
    }
    if (url.pathname.endsWith("/api/knowledge/datasets") && method === "POST") {
      const body = request.postDataJSON() as {
        name: string;
        description?: string;
      };
      const created = {
        id: "dataset-created",
        name: body.name,
        description: body.description ?? "",
        document_count: 0,
        chunk_count: 0,
      };
      datasets = [...datasets, created];
      return fulfillJson(route, { code: 0, data: created });
    }
    if (url.pathname.endsWith("/api/knowledge/datasets") && method === "GET") {
      return fulfillJson(route, {
        code: 0,
        data: datasets,
        total: datasets.length,
      });
    }
    return route.fallback();
  });
}

test("knowledge list is reachable, declares sharing, and updates from SSE", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  mockKnowledgeAPI(page, {
    datasets: [
      {
        id: "dataset-1",
        name: "Policies",
        description: "Shared employee policies",
        document_count: 2,
        chunk_count: 12,
      },
    ],
  });

  await page.goto("/workspace/chats/new");
  await page.getByRole("link", { name: "Knowledge" }).click();
  await expect(page).toHaveURL(/\/workspace\/knowledge$/);
  await expect(page.getByText(/shared by all DeerFlow users/i)).toBeVisible();
  await expect(page.getByText("Policies", { exact: true })).toBeVisible();
  await expect(page.getByText(/Parsing 1\/2/i)).toBeVisible();
});

test("user creates a dataset and admin can delete it", async ({ page }) => {
  mockLangGraphAPI(page);
  mockKnowledgeAPI(page, { datasets: [] });

  await page.goto("/workspace/knowledge");
  await page
    .getByRole("button", { name: "New knowledge base" })
    .first()
    .click();
  await page.getByPlaceholder("e.g. Product documentation").fill("Engineering");
  await page
    .getByPlaceholder(/Describe its contents/i)
    .fill("Architecture docs");
  await page.getByRole("button", { name: "Create", exact: true }).click();
  await expect(page.getByText("Engineering")).toBeVisible();

  const card = page.getByTestId("dataset-dataset-created");
  await card.getByRole("button", { name: "Delete knowledge base" }).click();
  await page.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(card).toHaveCount(0);
});

test("dataset detail uploads, parses, and links unsupported work to RAGFlow", async ({
  page,
}) => {
  mockLangGraphAPI(page);
  mockKnowledgeAPI(page, {
    datasets: [
      {
        id: "dataset-1",
        name: "Policies",
        description: "Shared employee policies",
        document_count: 1,
        chunk_count: 6,
        done_count: 1,
      },
    ],
    documents: [
      {
        id: "document-1",
        name: "handbook.pdf",
        run: "DONE",
        size: 4096,
        chunk_count: 6,
        update_time: 1_786_000_000_000,
      },
    ],
  });

  await page.goto("/workspace/knowledge/dataset-1");
  await expect(page.getByText("handbook.pdf")).toBeVisible();
  await page.getByLabel("handbook.pdf").check();
  await page.getByRole("button", { name: "Parse selected" }).click();
  await expect(page.getByText("Parsing started")).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles({
    name: "uploaded.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("content"),
  });
  await expect(page.getByText("uploaded.txt")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open in RAGFlow" })).toHaveCount(
    5,
  );
  await expect(
    page.getByRole("link", { name: "Open in RAGFlow" }).first(),
  ).toHaveAttribute("href", "http://ragflow.example");
});
