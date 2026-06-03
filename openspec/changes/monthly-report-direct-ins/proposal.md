## Why

月报功能当前通过 integrations 平台的 CLI 子进程桥接获取数据——每月的每一天发起 2 次子进程调用（一次获取趋势数据，一次做 KPI 聚合），一个 30 天的月报需要 **60 次子进程调用**，每次都要启动 Python 进程、加载配置、初始化 adapter、调用 InS API、然后销毁。这不仅极慢，而且将月报数据获取的核心能力耦合在 integrations 的 CLI 通道上。月报脚本已经在沙箱内运行，完全有能力直接调用 InS API 获取所需数据，无需绕道 integrations。

## What Changes

- 恢复 `_ins_provider.py` 中 `fetch_monthly_payload` 同步包装器的直接 InS 调用实现（当前已被替换为 `NotImplementedError` 桩）
- 新增 `DirectInsMonthlyProvider`，在 `_data_provider_impls.py` 中注册为 `monthly` 数据源的 `ins` 模式
- 修改 `_data_providers.py` 中的 `_resolve_mode`，使月报（以及日/周报）不再被硬编码固定为 `platform` 模式，改为支持通过 `DEER_FLOW_DATA_PROVIDER` 环境变量选择 `ins`（直连）或 `platform`（通过 integrations CLI）
- 月报查询脚本 `query_monthly.py` 的接口和输出契约保持不变
- **BREAKING**: 移除 `_platform_bridge.py` 中的 `call_action` 对月报 KPI 聚合的支持（月报改用直连后不再需要）

## Capabilities

### New Capabilities

- `monthly-report-direct-ins-provider`: 月报直连 InS 数据提供器，复用 `_ins_provider.py` 已有的异步编排逻辑（组件树查询、趋势数据批量拉取、KPI 聚合、机泵事件获取），将月报数据获取从 integrations CLI 子进程调用改为进程内直连 InS API

### Modified Capabilities

- `equipment-report-data-provider`: 日/周/月报数据源的 mode 解析从硬编码 `platform` 改为支持 `DEER_FLOW_DATA_PROVIDER` 环境变量选择（`ins` | `platform`），`platform` 保持为默认值以保证向后兼容

## Impact

- **Affected files**: `skills/custom/monthly-report/scripts/_ins_provider.py`, `skills/custom/monthly-report/scripts/_data_providers.py`, `skills/custom/monthly-report/scripts/_data_provider_impls.py`（日/周报使用各自的 `_ins_provider.py` 和 `_data_providers.py` 副本，不受影响）
- **No API changes**: 月报的输入 CLI 参数和输出 JSON schema 保持不变
- **No frontend changes**
- **Config change**: 用户可通过 `DEER_FLOW_DATA_PROVIDER=ins` 启用直连模式；不设置则保持当前 `platform` 行为
