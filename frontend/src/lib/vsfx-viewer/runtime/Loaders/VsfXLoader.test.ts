import { describe, expect, test, vi } from "vitest";

import { VsfXLoader } from "@/lib/vsfx-viewer/runtime/Loaders/VsfXLoader";

describe("VsfXLoader", () => {
  test("routes binary data to parseVsfx", async () => {
    const data = new Uint8Array([1, 2, 3, 4]).buffer;
    const parseVsfx = vi.fn();
    const emit = vi.fn();

    const loader = new VsfXLoader({
      emit,
      getVisualizeViewer: () => ({ parseVsfx }),
    });

    await loader.load({ data, filename: "assembly.vsfx" });

    expect(parseVsfx).toHaveBeenCalledWith(new Uint8Array(data));
    expect(emit).toHaveBeenCalledWith("geometrystart", {
      filename: "assembly.vsfx",
    });
    expect(emit).toHaveBeenCalledWith("geometryend", {
      filename: "assembly.vsfx",
    });
  });

  test("emits geometryerror when parse fails", async () => {
    const error = new Error("bad vsfx");
    const emit = vi.fn();

    const loader = new VsfXLoader({
      emit,
      getVisualizeViewer: () => ({
        parseVsfx: vi.fn(() => {
          throw error;
        }),
      }),
    });

    await expect(
      loader.load({
        data: new Uint8Array([9, 9, 9]).buffer,
        filename: "broken.vsfx",
      }),
    ).rejects.toThrow(error);

    expect(emit).toHaveBeenCalledWith("geometryerror", {
      error,
      filename: "broken.vsfx",
    });
  });
});
