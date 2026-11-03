import { beforeEach, expect, it, rs } from "@rstest/core";
import { act, renderHook, waitFor } from "@testing-library/react";

import { useModelControl } from "@/core/models/use-model-control";

const mocks = rs.hoisted(() => ({ resolve: rs.fn(), error: rs.fn() }));
rs.mock("@/core/models/control", () => ({
  maySelectModel: () => true,
  resolveModelControl: mocks.resolve,
}));
rs.mock("sonner", () => ({ toast: { error: mocks.error } }));
const ambiguous = {
  status: "ambiguous",
  scope: "turn",
  query: "demo",
  model_name: null,
  candidates: [
    { name: "B", label: "Model B" },
    { name: "C", label: "Model C" },
  ],
};

beforeEach(() => {
  mocks.resolve.mockReset();
  mocks.error.mockReset();
});

it("waits for a user choice and revalidates it before resolving", async () => {
  mocks.resolve.mockResolvedValueOnce(ambiguous).mockResolvedValueOnce({
    ...ambiguous,
    status: "resolved",
    model_name: "B",
  });
  const { result } = renderHook(() => useModelControl("alice:t1", "en"));
  let pending!: ReturnType<typeof result.current.prepare>;
  act(() => {
    pending = result.current.prepare("use demo");
  });
  await waitFor(() => expect(result.current.request).not.toBeNull());
  expect(mocks.resolve).toHaveBeenCalledTimes(1);
  act(() =>
    result.current.choose({
      version: 1,
      kind: "human_input_response",
      source: "model_selection",
      request_id: result.current.request!.request_id,
      response_kind: "option",
      option_id: "B",
      value: "B",
    }),
  );
  await act(async () => {
    expect((await pending)?.model_name).toBe("B");
  });
  expect(mocks.resolve.mock.calls[1]?.[1]).toEqual({ model_name: "B" });
});

it("account or conversation changes cancel pending choices quietly", async () => {
  mocks.resolve.mockResolvedValue(ambiguous);
  const { result, rerender } = renderHook(
    ({ owner }) => useModelControl(owner, "en"),
    { initialProps: { owner: "alice:t1" } },
  );
  let pending!: Promise<unknown>;
  act(() => {
    pending = result.current.prepare("use demo").catch((e: Error) => e.message);
  });
  await waitFor(() => expect(result.current.request).not.toBeNull());
  rerender({ owner: "bob:t2" });
  await act(async () => {
    expect(await pending).toBe("model-selection-cancelled");
  });
  expect(result.current.request).toBeNull();
  expect(mocks.resolve).toHaveBeenCalledTimes(1);
  expect(mocks.error).not.toHaveBeenCalled();
});

it("shows authorization or service errors instead of silently dropping the send", async () => {
  mocks.resolve.mockRejectedValue(
    new Error("Model is not available for your role"),
  );
  const { result } = renderHook(() => useModelControl("alice:t1", "en"));
  await act(async () => {
    await expect(result.current.prepare("use demo")).rejects.toThrow(
      "not available",
    );
  });
  expect(mocks.error).toHaveBeenCalledWith(
    "Model is not available for your role",
  );
  expect(result.current.busy).toBe(false);
});
