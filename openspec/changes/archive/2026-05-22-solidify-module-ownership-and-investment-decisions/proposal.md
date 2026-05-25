## Why

当前能力矩阵中的 owner 全部是"建议角色"而非真实负责人，模块状态（Core/Scale-Up/Stabilize/Incubate）和 Q3 投资结论也尚未经过正式确认。这导致模块责任漂浮、排期缺乏归属、月度评审缺乏可引用的正式台账。6 月路线图的退出标准明确要求"有一版真实 owner 与模块状态矩阵"，本 change 就是交付这份正式台账。

## What Changes

- 将能力矩阵中 18 个模块的"建议业务 Owner"和"建议技术 Owner"替换为真实岗位或真实人员姓名
- 为每个模块标注当前状态（Core / Scale-Up / Stabilize / Incubate）和 Q3 投资结论（继续投入 / 维持 / 缩减 / 停投）
- 将仍未定责的模块显式列为管理风险
- 形成可直接用于月度评审和排期的正式台账文档
- **BREAKING**: 任何模块若无法确定真实 owner，将标记为"无主模块"并列入管理风险清单

## Capabilities

### New Capabilities
- `module-ownership-ledger`: 模块归属台账——每个模块有真实 owner、状态标签和投资结论，无主模块显式暴露

### Modified Capabilities
<!-- 本 change 不修改任何已有 spec 的行为要求，仅补充治理层文档 -->

## Impact

- 受影响文档：`docs/system-capability-matrix.md`（从建议版升级为正式台账）
- 受影响流程：月度评审、排期决策、模块责任归属
- 不涉及代码变更
- 依赖 ISSUE-01（主流程与对象模型基线已完成）作为分类依据
