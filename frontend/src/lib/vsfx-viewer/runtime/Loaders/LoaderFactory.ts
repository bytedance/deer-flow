import type { BaseLoader } from "./BaseLoader";
import type { LoaderContext } from "./BaseLoader";
import { VsfXLoader } from "./VsfXLoader";

export class LoaderFactory {
  static create(filename: string, context: LoaderContext): BaseLoader {
    if (filename.toLowerCase().endsWith(".vsfx")) {
      return new VsfXLoader(context);
    }

    throw new Error(`Unsupported viewer asset type: ${filename}`);
  }
}
