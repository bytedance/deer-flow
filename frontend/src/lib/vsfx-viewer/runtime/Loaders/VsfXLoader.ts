import type { ViewerBinarySource } from "@/lib/vsfx-viewer/viewer-core";

import { BaseLoader } from "./BaseLoader";

export class VsfXLoader extends BaseLoader {
  async load(source: ViewerBinarySource) {
    const viewer = this.context.getVisualizeViewer();
    const parseVsfx = viewer?.parseVsfx;

    if (typeof parseVsfx !== "function") {
      throw new Error("Visualize viewer does not expose parseVsfx()");
    }

    this.context.emit("geometrystart", { filename: source.filename });
    this.context.emit("databasechunk", source);

    try {
      await Promise.resolve(parseVsfx.call(viewer, new Uint8Array(source.data)));
      this.context.emit("geometryend", { filename: source.filename });
    }
    catch (error) {
      const normalizedError =
        error instanceof Error ? error : new Error("Failed to parse VSFX data");
      this.context.emit("geometryerror", {
        error: normalizedError,
        filename: source.filename,
      });
      throw normalizedError;
    }
  }
}
