import { prepareDocument } from "./prepare-document.js";
import { transferBuffers } from "./document-model.js";

self.onmessage = async ({ data: { bytes, kind } }) => {
  try {
    const result = await prepareDocument(bytes, kind, (phase) =>
      self.postMessage({ phase }),
    );
    self.postMessage({ result }, transferBuffers(result));
  } catch {
    // Parser exceptions can contain document contents: expose a fixed diagnostic.
    self.postMessage({
      error:
        "Office file exceeds preview limits or cannot be read. Download the original to open it.",
    });
  }
};
