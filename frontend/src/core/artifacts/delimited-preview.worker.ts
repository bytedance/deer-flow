import { parseDelimitedPreview } from "./delimited-preview";
import {
  type DelimitedPreviewInput,
  type DelimitedPreviewResponse,
} from "./delimited-preview-types";

self.onmessage = (event: MessageEvent<DelimitedPreviewInput>) => {
  let response: DelimitedPreviewResponse;
  try {
    response = { result: parseDelimitedPreview(event.data) };
  } catch {
    response = { error: "Unable to reliably preview this delimited file" };
  }
  self.postMessage(response);
};
