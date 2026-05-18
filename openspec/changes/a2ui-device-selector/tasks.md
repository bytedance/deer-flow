## 1. 后端 OrganizeServiceClient

- [x] 1.1 新增 `backend/packages/harness/deerflow/rpc/organize_service.py`，实现 `OrganizeServiceClient` 类，封装 `ins-bus-rpc` 服务的 `/organize/getOrgTreeByUserIdAndOrgId` 接口
- [x] 1.2 编写 `backend/tests/test_organize_service.py` 单元测试，mock RpcClient 验证参数传递和响应解包

## 2. 前端共享类型与组织树组件

- [x] 2.1 定义 `OrgTreeNode` 接口和相关类型（id, label, type, path, parentId, displayOrder, children 等）
- [x] 2.2 在 `frontend/src/components/genui/` 下新增 `OrgTreePanel.tsx`，实现左侧可折叠组织树面板（仅展示 type>=10 的组织节点，递归渲染，点击展开/折叠，点击组织节点通知右侧面板切换）

## 3. 前端 DeviceSelectorBlock（单选）

- [x] 3.1 新增 `frontend/src/components/genui/DeviceSelectorBlock.tsx`，实现左右分栏设备单选选择器（遵循 FormBlock 的交互组件模式：接收 block 含 props/treeData/onInteraction/interactionState）
- [x] 3.2 左侧嵌入 OrgTreePanel，右侧为设备列表：选中组织节点后展示其下所有 type<10 设备节点，点击设备项即标记选中
- [x] 3.3 实现单选回调：点击右侧设备 → 高亮选中 → 调用 onInteraction 回传 `{ selected: { id, label, type, path } }`
- [x] 3.4 处理 interactionState 状态（loading/submitted/expired/readonly）

## 4. 前端 DeviceSelectorMultiBlock（多选）

- [x] 4.1 新增 `frontend/src/components/genui/DeviceSelectorMultiBlock.tsx`，实现左右分栏设备多选选择器（布局同单选）
- [x] 4.2 右侧设备列表以复选框展示，支持 toggle 选中/取消，跨组织节点保留已选设备
- [x] 4.3 实现提交逻辑：底部显示已选计数 + 提交按钮 → onInteraction 回传 `{ selected: [{ id, label, type, path }] }`
- [x] 4.4 支持 maxSelect 限制可选数量上限（超出时禁用剩余复选框）

## 5. 注册与校验

- [x] 5.1 在 `frontend/src/core/genui/registry.ts` 的 `COMPONENT_REGISTRY` 中注册 `device-selector` 和 `device-selector-multi` 两个懒加载组件
- [x] 5.2 在 `frontend/src/core/genui/sanitizer.ts` 的 `ALLOWED_PROPS_BY_COMPONENT` 中添加两个新组件的 props 白名单（treeData, title, maxSelect）
- [x] 5.3 在 `frontend/src/core/genui/validator.ts` 中添加 `deviceSelectorPropsSchema` 和 `deviceSelectorMultiPropsSchema` 的 Zod schema（含 treeData 数组校验、树节点必填字段 id/label/type 校验），并注册到 `propsSchemas`

## 6. 集成验证

- [x] 6.1 运行 `pnpm check`（lint + typecheck）确认前端无类型错误
- [x] 6.2 运行 `make test`（backend）确认后端测试通过
- [x] 6.3 在 A2UI 调试面板中验证两个组件可正常渲染和交互
