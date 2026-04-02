import { classifyVsfxArtifactPath } from "@/core/artifacts/vsfx/classify";

import type { BaseLoader } from "./BaseLoader";
import type { LoaderContext } from "./BaseLoader";
import { VsfXLoader } from "./VsfXLoader";

export class LoaderFactory {
  static create(filename: string, context: LoaderContext): BaseLoader {
    if (classifyVsfxArtifactPath(filename).kind === "vsfx") {
      return new VsfXLoader(context);
    }

    throw new Error(`Unsupported viewer asset type: ${filename}`);
  }
}
