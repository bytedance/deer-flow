import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, renderHook } from "@testing-library/react";

import { useDelimitedPreview } from "@/core/artifacts/use-delimited-preview";

class FakeWorker {
  static instances: FakeWorker[] = [];
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessageerror: (() => void) | null = null;
  postMessage = rs.fn();
  terminate = rs.fn();
  constructor() {
    FakeWorker.instances.push(this);
  }
  complete() {
    this.onmessage?.({ data: { result: sample } } as MessageEvent);
  }
}
const sample = {
  rows: [["a"]],
  columnCount: 1,
  limited: false,
  unevenRows: false,
};
const input = {
  content: "a",
  delimiter: "," as const,
  truncated: false,
  active: true,
  identity: "file-a",
};
const lastWorker = () => FakeWorker.instances.at(-1)!;

describe("useDelimitedPreview", () => {
  beforeEach(() => {
    FakeWorker.instances = [];
    rs.stubGlobal("Worker", FakeWorker);
    rs.useFakeTimers();
  });
  afterEach(() => {
    cleanup();
    rs.useRealTimers();
    rs.unstubAllGlobals();
  });
  it("starts only while active, reuses success, and ignores unrelated renders", () => {
    const { result, rerender } = renderHook(useDelimitedPreview, {
      initialProps: { ...input, active: false },
    });
    expect(FakeWorker.instances).toHaveLength(0);
    rerender(input);
    expect(result.current.status).toBe("loading");
    act(() => lastWorker().complete());
    expect(result.current.result).toEqual(sample);
    expect(lastWorker().terminate).toHaveBeenCalledTimes(1);
    rerender({ ...input });
    rerender({ ...input, active: false });
    rerender(input);
    expect(FakeWorker.instances).toHaveLength(1);
    expect(result.current.status).toBe("ready");
  });
  it("terminates on input changes and rejects late responses", () => {
    const { result, rerender } = renderHook(useDelimitedPreview, {
      initialProps: input,
    });
    const old = lastWorker();
    const late = old.onmessage!;
    rerender({ ...input, identity: "file-b" });
    expect(old.terminate).toHaveBeenCalled();
    expect(result.current.result).toBeUndefined();
    act(() => late({ data: { result: sample } } as MessageEvent));
    expect(result.current.result).toBeUndefined();
    act(() => lastWorker().complete());
    expect(result.current.result).toEqual(sample);
    rerender({ ...input, identity: "file-c" });
    expect(result.current.result).toBeUndefined();
  });
  it("cancels pending work when hidden and on unmount", () => {
    const { rerender, unmount } = renderHook(useDelimitedPreview, {
      initialProps: input,
    });
    const first = lastWorker();
    rerender({ ...input, active: false });
    expect(first.terminate).toHaveBeenCalled();
    rerender(input);
    const second = lastWorker();
    expect(second).not.toBe(first);
    unmount();
    expect(second.terminate).toHaveBeenCalled();
  });
  it("times out after 5 seconds and retries only on explicit request", () => {
    const { result, rerender } = renderHook(useDelimitedPreview, {
      initialProps: input,
    });
    act(() => {
      rs.advanceTimersByTime(4999);
    });
    expect(result.current.status).toBe("loading");
    act(() => {
      rs.advanceTimersByTime(1);
    });
    expect(result.current.status).toBe("error");
    expect(lastWorker().terminate).toHaveBeenCalled();
    rerender({ ...input, active: false });
    rerender(input);
    expect(FakeWorker.instances).toHaveLength(1);
    act(() => result.current.retry());
    expect(FakeWorker.instances).toHaveLength(2);
    act(() => lastWorker().complete());
    expect(result.current.status).toBe("ready");
  });
  it("surfaces unavailable workers and worker syntax/load/message errors", () => {
    const { result } = renderHook(useDelimitedPreview, { initialProps: input });
    act(() => lastWorker().onerror?.());
    expect(result.current.status).toBe("error");
    act(() => result.current.retry());
    act(() =>
      lastWorker().onmessage?.({ data: { error: "syntax" } } as MessageEvent),
    );
    expect(result.current.status).toBe("error");
    act(() => result.current.retry());
    act(() => lastWorker().onmessageerror?.());
    expect(result.current.status).toBe("error");
    rs.stubGlobal("Worker", undefined);
    act(() => result.current.retry());
    expect(result.current.status).toBe("error");
  });
  it("invalidates a result on content, delimiter, or truncation changes", () => {
    const { result, rerender } = renderHook(useDelimitedPreview, {
      initialProps: { ...input, delimiter: input.delimiter as "," | "\t" },
    });
    act(() => lastWorker().complete());
    rerender({ ...input, content: "b" });
    expect(result.current.result).toBeUndefined();
    act(() => lastWorker().complete());
    rerender({ ...input, content: "b", delimiter: "\t" });
    expect(result.current.result).toBeUndefined();
    act(() => lastWorker().complete());
    rerender({ ...input, content: "b", delimiter: "\t", truncated: true });
    expect(result.current.result).toBeUndefined();
    expect(FakeWorker.instances).toHaveLength(4);
  });
  it("caps input before posting without splitting a surrogate pair", () => {
    renderHook(useDelimitedPreview, {
      initialProps: { ...input, content: "a".repeat(1_048_575) + "😀tail" },
    });
    expect(lastWorker().postMessage).toHaveBeenCalledWith({
      content: "a".repeat(1_048_575),
      delimiter: ",",
      truncated: true,
    });
  });
});
