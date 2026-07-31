import { afterEach, describe, expect, it, rs } from "@rstest/core";

import { LatestBrowserFrameBuffer } from "@/components/workspace/browser-view/frame-buffer";

describe("LatestBrowserFrameBuffer", () => {
  afterEach(() => {
    rs.restoreAllMocks();
    rs.unstubAllGlobals();
  });

  it("publishes only the latest binary frame in one animation frame", () => {
    let scheduled: FrameRequestCallback | undefined;
    const requestFrame = rs.fn((callback: FrameRequestCallback) => {
      scheduled = callback;
      return 7;
    });
    rs.stubGlobal("requestAnimationFrame", requestFrame);
    rs.stubGlobal("cancelAnimationFrame", rs.fn());
    const createObjectURL = rs
      .spyOn(URL, "createObjectURL")
      .mockReturnValueOnce("blob:first");
    const revokeObjectURL = rs.spyOn(URL, "revokeObjectURL");
    const listener = rs.fn();
    const frames = new LatestBrowserFrameBuffer();
    frames.subscribe(listener);
    const dropped = new Blob(["dropped"], { type: "image/jpeg" });
    const latest = new Blob(["latest"], { type: "image/jpeg" });

    frames.push(dropped);
    frames.push(latest);

    expect(requestFrame).toHaveBeenCalledOnce();
    expect(listener).not.toHaveBeenCalled();
    scheduled?.(16);
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(createObjectURL).toHaveBeenCalledWith(latest);
    expect(frames.getSnapshot()).toBe("blob:first");
    expect(listener).toHaveBeenCalledOnce();
    expect(revokeObjectURL).not.toHaveBeenCalled();
  });

  it("revokes replaced and disposed object URLs", () => {
    const callbacks: FrameRequestCallback[] = [];
    rs.stubGlobal(
      "requestAnimationFrame",
      rs.fn((callback: FrameRequestCallback) => {
        callbacks.push(callback);
        return callbacks.length;
      }),
    );
    rs.stubGlobal("cancelAnimationFrame", rs.fn());
    rs.spyOn(URL, "createObjectURL")
      .mockReturnValueOnce("blob:first")
      .mockReturnValueOnce("blob:second");
    const revokeObjectURL = rs.spyOn(URL, "revokeObjectURL");
    const frames = new LatestBrowserFrameBuffer();

    frames.push(new Blob(["one"]));
    callbacks.shift()?.(16);
    frames.push(new Blob(["two"]));
    callbacks.shift()?.(32);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:first");

    frames.dispose();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:second");
    expect(frames.getSnapshot()).toBeNull();
  });
});
