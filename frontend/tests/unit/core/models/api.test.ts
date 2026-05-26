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
