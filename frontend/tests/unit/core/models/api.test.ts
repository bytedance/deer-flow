import { beforeEach, expect, test, vi } from "vitest";

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

test("updateModel encodes the model name in the URL path", async () => {
  fetchMock.mockResolvedValue({
    ok: true,
    json: async () => ({ name: "openai/gpt 4o", model: "gpt-4o" }),
  });

  const { updateModel } = await import("@/core/models/api");

  await updateModel({
    name: "openai/gpt 4o",
    payload: { name: "openai/gpt 4o", model: "gpt-4o" },
  });

  expect(fetchMock).toHaveBeenCalledWith(
    expect.stringContaining("/api/models/openai%2Fgpt%204o"),
    expect.objectContaining({ method: "PUT" }),
  );
});

test("deleteModel encodes the model name in the URL path", async () => {
  fetchMock.mockResolvedValue({
    ok: true,
    json: async () => ({ status: "ok" }),
  });

  const { deleteModel } = await import("@/core/models/api");

  await deleteModel("openai/gpt 4o");

  expect(fetchMock).toHaveBeenCalledWith(
    expect.stringContaining("/api/models/openai%2Fgpt%204o"),
    expect.objectContaining({ method: "DELETE" }),
  );
});

test("detectModels sends an explicit null API key when omitted", async () => {
  fetchMock.mockResolvedValue({
    ok: true,
    json: async () => ({ endpoint: "https://api.example.com", models: [] }),
  });

  const { detectModels } = await import("@/core/models/api");

  await detectModels({ baseUrl: "https://api.example.com" });

  expect(fetchMock).toHaveBeenCalledWith(
    expect.stringContaining("/api/models/detect"),
    expect.objectContaining({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        base_url: "https://api.example.com",
        api_key: null,
      }),
    }),
  );
});

test("createModel surfaces backend validation errors", async () => {
  fetchMock.mockResolvedValue({
    ok: false,
    statusText: "Bad Request",
    json: async () => ({ detail: "Model name already exists" }),
  });

  const { createModel } = await import("@/core/models/api");

  await expect(
    createModel({ name: "gpt-4o", model: "openai:gpt-4o" }),
  ).rejects.toThrow("Model name already exists");
});
