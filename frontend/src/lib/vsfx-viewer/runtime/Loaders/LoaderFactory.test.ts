import { describe, expect, test, vi } from "vitest";

import { LoaderFactory } from "./LoaderFactory";

describe("LoaderFactory", () => {
  test("uses the VSFX classifier helper for mixed-case .vsfx filenames", () => {
    const loader = LoaderFactory.create("/artifacts/SAMPLE.VSFX", {
      emit: vi.fn(),
      getVisualizeViewer: () => null,
    });

    expect(loader.constructor.name).toBe("VsfXLoader");
  });
});
