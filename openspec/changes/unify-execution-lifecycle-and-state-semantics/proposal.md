## Why

当前 thread、run、upload、artifact 在前端和后端的状态名称、含义和失败语义各自独立定义，用户无法准确区分"执行中、已完成、失败、外部依赖不可用、等待索引、等待人工处理"等状态，运维也无法从日志和事件中定位同一条主链上的失败位置。在 ISSUE-01 定义了主对象模型后，需要立即统一状态语义，否则后续跳转链路和知识主链无法建立在一致的基础上。

## What Changes

- 统一 thread、run、upload、artifact 的前后端状态名称与含义
- 定义统一的失败分类：执行失败、上传失败、外部依赖不可用，以及每类的可恢复动作
- 用户可在主链中看到失败发生在哪一层，及下一步动作
- 关键状态映射和错误语义具备回归测试覆盖
- **BREAKING**: 前端和后端可能存在状态枚举值变更，需协调发布

## Capabilities

### New Capabilities

- `execution-lifecycle-states`: 统一的 thread/run/upload/artifact 生命周期状态枚举与语义定义
- `failure-classification`: 统一失败分类体系：执行失败、上传失败、外部依赖不可用，含可恢复动作
- `state-traceability`: 主链失败定位与层标识机制，用户和运维可识别失败发生在哪一层

### Modified Capabilities

<!-- 涉及对现有模块状态字段的收敛，可能影响 closed-loop-tickets、equipment-report-data-provider 中已有的状态定义 -->

## Impact

- 影响所有使用 thread、run、upload、artifact 状态的前端组件和后端 API
- 网关错误透传逻辑需要对齐新的失败分类
- 日志和监控需要适配统一状态口径
- 依赖 ISSUE-01 的主对象模型基线
