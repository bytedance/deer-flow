import type { IViewer } from "@/lib/vsfx-viewer/viewer-core";

import { OdaGeAction } from "../Common/OdaGeAction";

export class PanAction extends OdaGeAction {
  constructor(viewer: IViewer) {
    super(viewer);
  }
}
