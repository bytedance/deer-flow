export interface OrgTreeNode {
  id: string;
  label: string;
  type: number;
  path: string;
  parentId: string;
  displayOrder?: number;
  hiddenFlag?: number;
  authFlag?: boolean;
  children?: OrgTreeNode[];
}

export interface SelectedDevice {
  id: string;
  label: string;
  type: number;
  path: string;
}

export interface DeviceQueryParams {
  userId?: string;
  orgId?: number;
  treeType?: number;
  typeId?: number;
}
