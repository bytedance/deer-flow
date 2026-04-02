import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import { OdaGeAction } from "../Common/OdaGeAction";

export class ZoomAction extends OdaGeAction {
  constructor(viewer: IViewer) {
    super(viewer);
  }
}
