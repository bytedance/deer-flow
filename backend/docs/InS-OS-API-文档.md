# InS OS 系统接口文档汇总

> 整理时间: 2026-05-20
> 涵盖项目: ui-view、ui-manage、ui-ehm

---

## 目录

- [一、ui-view (数据展示层)](#一ui-view-数据展示层)
  - [架构概览](#架构概览)
  - [1. 认证与用户](#1-认证与用户)
  - [2. 数据查询（2K/旋转设备）](#2-数据查询2k旋转设备)
  - [3. 告警事件](#3-告警事件)
  - [4. 事件确认](#4-事件确认)
  - [5. 历史数据](#5-历史数据)
  - [6. 实时数据](#6-实时数据)
  - [7. 运行状态](#7-运行状态)
  - [8. 系统设置](#8-系统设置)
  - [9. 6K 静态测厚计划](#9-6k-静态测厚计划)
  - [10. 6K 腐蚀/测厚数据](#10-6k-腐蚀测厚数据)
  - [11. 6K 静态报告](#11-6k-静态报告)
  - [12. 7K 静态设备](#12-7k-静态设备)
  - [13. 8K 大型旋转机械数据](#13-8k-大型旋转机械数据)
  - [14. 8K 事件](#14-8k-事件)
  - [15. 8K 润滑油报告](#15-8k-润滑油报告)
  - [16. 9K 往复机械数据](#16-9k-往复机械数据)
  - [17. 9K 事件](#17-9k-事件)
  - [18. 通用事件评论](#18-通用事件评论)
  - [19. 诊断事件与报告工具](#19-诊断事件与报告工具)
  - [20. 专家库](#20-专家库)
  - [21. 工作流/审批](#21-工作流审批)
  - [22. 设备设置与组织结构](#22-设备设置与组织结构)
  - [23. 数据字典](#23-数据字典)
  - [24. 组织查询](#24-组织查询)
  - [25. 8K 组织管理](#25-8k-组织管理)
  - [26. 融智第三方认证](#26-融智第三方认证)
  - [27. 外部直调接口](#27-外部直调接口)
- [二、ui-manage (系统管理端)](#二ui-manage-系统管理端)
  - [架构概览](#架构概览-1)
  - [1. 认证登录](#1-认证登录)
  - [2. 用户管理](#2-用户管理)
  - [3. 组织管理](#3-组织管理)
  - [4. 角色管理](#4-角色管理)
  - [5. 菜单管理](#5-菜单管理)
  - [6. 系统配置](#6-系统配置)
  - [7. 字典类型](#7-字典类型)
  - [8. 字典数据](#8-字典数据)
  - [9. 同步管理](#9-同步管理)
  - [10. 采集器管理](#10-采集器管理)
  - [11. 设备设置（机器/组件/测点）](#11-设备设置机器组件测点)
  - [12. 8K 组织导出](#12-8k-组织导出)
  - [13. 文件上传](#13-文件上传)
  - [14. 接口订阅](#14-接口订阅)
  - [15. 总貌图](#15-总貌图)
  - [16. 数据字典（新版）](#16-数据字典新版)
  - [17. 石化通推送](#17-石化通推送)
  - [18. 推送日志错误](#18-推送日志错误)
  - [19. 微信推送目标](#19-微信推送目标)
  - [20. 微信代理](#20-微信代理)
  - [21. 通用消息组](#21-通用消息组)
  - [22. 工作流设置](#22-工作流设置)
  - [23. 数据备份](#23-数据备份)
  - [24. 数据恢复](#24-数据恢复)
  - [25. 工具集（轴承库/报告/案例库等）](#25-工具集轴承库报告案例库等)
  - [26. 专家库](#26-专家库)
- [三、ui-ehm (设备健康管理)](#三ui-ehm-设备健康管理)
  - [架构概览](#架构概览-2)
  - [1. EHM 认证与用户](#1-ehm-认证与用户)
  - [2. 路由配置](#2-路由配置)
  - [3. 工作台列表数据](#3-工作台列表数据)
  - [4. 组织结构树](#4-组织结构树)
  - [5. 统计数据](#5-统计数据)
  - [6. 工作台视图 CRUD](#6-工作台视图-crud)
  - [7. EHM Demo](#7-ehm-demo)
  - [8. 案例数据库](#8-案例数据库)
  - [9. MQTT 配置](#9-mqtt-配置)

---

# 一、ui-view (数据展示层)

## 架构概览

| 项目 | 说明 |
|------|------|
| 基础路径 | `INS_CONFIG.SERVER_URL` (如 `http://host:port/ins-os-view`) |
| HTTP 库 | Axios（5个插件实例） |
| 认证方式 | Bearer JWT Token，自动刷新 |
| 刷新端点 | `GET /refresh` |
| 公共拦截器 | 自动注入 `factoryId`（除 login/captcha 外） |

**5个HTTP服务插件：**

| 插件名 | 基础URL | 用途 |
|--------|---------|------|
| `http-service` | `INS_CONFIG.SERVER_URL` | 通用请求 |
| `http-service-common` | 动态(工厂模式) | 通用请求(带拦截器) |
| `http-service-delete` | `/ins-data-delete` | 数据删除 |
| `http-service-download` | `INS_CONFIG.serverIp` | 文件下载 |
| `http-service-upload` | 动态(工厂模式) | 文件上传 |

---

### 1. 认证与用户

**文件:** `src/api/sys.authority.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/login` | POST | 用户登录 | `params: Object` (登录凭证) |
| 2 | `/sendAuthCode.do` | POST | 获取短信验证码 | `params: Object` |
| 3 | `/captcha` | GET | 获取图形验证码 | 无 |
| 4 | `/user/checkPasswordReset` | GET | 检查是否需要重置密码 | 无 |
| 5 | `/user/updatePwd` | POST | 修改用户密码 | `oldPassword: string`, `newPassword: string` |
| 6 | `/getInfo` | GET | 获取当前用户信息（角色/权限） | `params: Object` |
| 7 | `/getConfig` | GET | 获取系统配置 | `params: Object` |
| 8 | `/data/getFactoryInfoByUserId` | GET | 获取用户关联工厂信息 | `params: Object` |
| 9 | `/user/departActiveChart` | GET | 部门活跃用户登录统计 | `beginTime: number`, `endTime: number`, `factoryId?: string` |
| 10 | `/user/activeTrendChart` | GET | 活跃用户趋势图 | `params: Object` |
| 11 | `/user/activeList` | GET | 活跃用户列表 | `params: Object` |
| 12 | `/user/zombieList` | GET | 僵尸/不活跃用户列表 | `params: Object` |

---

### 2. 数据查询（2K/旋转设备）

**文件:** `src/api/page.data.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/artisan/checkComponents` | GET | 手动检查子设备故障 | `params: Object` |
| 2 | `/data/getEqptStatusRt` | GET | 查询设备实时状态 | `params: Object` |
| 3 | `/data/getEqptStatusChange` | GET | 查询设备历史状态变更事件 | `params: Object` |
| 4 | `/data/getUserAlarmEventList` | GET | 查询告警事件列表 | `params: Object` |
| 5 | `/data/getTrendDataHis` | GET | 查询趋势图历史数据（2K系统） | `params: Object` |
| 6 | `/data/getWaveDataHis` | GET | 获取波形频谱数据 | `params: Object` |
| 7 | `/data/getWaveDataTimepoint` | GET | 获取存在波形数据的时间点 | `gpid: string`, `startTime`, `endTime` |
| 8 | `/data/getValueWithWave` | GET | 获取带波形的特征值数据 | `params: Object` |
| 9 | `/data/getMPWaveDataHisList` | GET | 获取多点波形数据 | `gpid: string`, `time` |
| 10 | `/data/getOverviewInfo` | GET | 获取总貌图标签页信息 | `params: Object` |
| 11 | `/data/getOverviewDetailInfo` | GET | 获取总貌图详细配置 | `params: Object` |
| 12 | `/data/getPosRtData` | GET | 获取测点实时数据与详情 | `params: Object` |
| 13 | `/excel/data/exportTrendData` | GET | 导出趋势图数据 | `params: Object` (返回blob) |
| 14 | `/excel/data/downloadWaveDataHis` | POST | 下载波形频谱图数据 | `data: Object` (返回blob) |
| 15 | `/data/getAlarmOverview` | GET | 首页-告警概览 | `params: Object` |
| 16 | `/data/getEventOverview` | GET | 首页-事件概览 | `params: Object` |
| 17 | `/data/getMachinesReportByDate` | GET | 按日期查询机器报告 | `params: Object` |
| 18 | `/excel/exportMachinesReportByDate` | GET | 导出机器报告 | `params: Object` (返回blob) |
| 19 | `/data/getDataReport2KList` | GET | 获取诊断数据列表 | `params: Object` |
| 20 | `/excel/exportDataReport2KList` | GET | 导出诊断数据列表 | `params: Object` (返回blob) |
| 21 | `/excel/exportFactoryReport` | GET | 导出工厂级报告 | `params: Object` (返回blob) |
| 22 | `/excel/pump/exportFactoryReport` | GET | 导出泵工厂级报告 | `params: Object` (返回blob) |
| 23 | `/excel/pump/moreDeviceReport` | GET | 导出泵多运行数据报告 | `params: Object` (返回blob) |
| 24 | `/static/tryDevOperatingStateList` | GET | 尝试获取泵工厂报告数据 | `params: Object` |
| 25 | `/data/getFactoryReport` | GET | 获取工厂级报告 | `params: Object` |
| 26 | `/data/getFactoryReportMoreInfoByMachineId` | GET | 按机器ID获取报告详情 | `params: Object` |
| 27 | `/data/refreshEqptStatusRt` | GET | 刷新设备实时状态 | `params: Object` |
| 28 | `/data/getMachineDataHisListPost` | POST | 获取智能诊断结果列表 | `machineId, gpids, typeList, currentPage, pageSize, noPage, startTime, endTime, includeFilter, density` |
| 29 | `/data/getWaveDataHisList` | GET | 获取多时间点波形数据 | `gpid: string`, `timeList: string` |
| 30 | `/artisan/getDiagnosticResultList` | GET | 获取智能诊断结果列表 | `params: Object` |
| 31 | `/data/deviceRtStatusExport` | GET | 导出2K实时状态列表 | `params: Object` (返回blob) |
| 32 | `/static/getTrendAlarmList` | GET | 获取设备趋势告警列表 | `params: Object` |
| 33 | `/excel/exportTrendAlarmList` | POST | 导出泵告警列表 | `params: Object` (返回blob) |
| 34 | `/static/getMachineStartStopList` | GET | 获取设备启停报告 | `params: Object` |
| 35 | `/excel/exportMachineStartStopList` | POST | 导出启停列表 | `params: Object` (返回blob) |
| 36 | `/intelligentDiagnosis/getDiagnosisListPage` | POST | 获取智能诊断分页列表 | `data: Object`, 10秒超时提醒 |
| 37 | `/intelligentDiagnosis/exportDiagnosisList` | POST | 导出智能诊断列表 | `data: Object` (返回blob) |
| 38 | `/intelligentDiagnosis/getPointInfoByComponentId` | GET | 按组件ID获取测点信息 | `params: Object` |
| 39 | `/data/getUserAlarmEventExport` | POST | 告警统计导出 | `params: Object` (返回blob) |

#### `/data/getTrendDataHis` 请求/响应说明

> 证据级别: 实测验证（2026-05-20）
>  
> 验证环境: `http://182.92.187.198`
>  
> 命中样例: `factoryId=390567939692036096`（盛虹炼化（连云港）有限公司）, `machineId=220302060634798`（封油泵-1110-P-1007A）, `gpid=2203020606347980001`（泵联端_V）

##### 请求特征

- 方法: `GET`
- 路径: `/ins-os-view/data/getTrendDataHis`
- 认证: `Authorization: Bearer <token>`
- 必填参数: `gpids`, `startTime`, `endTime`, `density`, `factoryId`
- 实测结论: `factoryId` 不可省略, 否则返回 `[工厂id不能为空]`
- 2K 实测默认参数: `density=1`

```http
GET /ins-os-view/data/getTrendDataHis?gpids=2203020606347980001&startTime=1778657107824&endTime=1779261907824&density=1&factoryId=390567939692036096
Authorization: Bearer <token>
```

##### 响应结构

- 顶层结构: `{ code, msg, data }`
- `data` 类型: `array`
- `data[0]` 为单个测点对象, 同时带测点告警阈值字段和时间序列字段
- `data[0].value` 类型: `array`
- `data[0].value[*]` 结构: `{ datatype, datatime, data_category, value }`
- `data[0].value[*].value` 类型: `array`
- 最内层特征值通过中文 `name` 区分, 2K 不会直接返回平铺后的 `v_rms` / `a_peak`

##### 关键字段

- `positionType=23`
- `data[0]` 包含阈值字段: `vRmsBValue`, `vRmsCValue`, `vRmsDValue`, `aPeakBValue`, `aPeakCValue`, `aPeakDValue` 等
- 本次 7 天时间窗内返回 `79` 个时间点
- 最内层实测特征名: `速度有效值`, `加速度峰值`

```json
{
  "msg": "操作成功",
  "code": 200,
  "data": [
    {
      "gpid": "2203020606347980001",
      "equipmentId": 220302060634798,
      "positionType": 23,
      "startTime": 1778657107824,
      "endTime": 1779261907824,
      "vRmsBValue": 1.8,
      "vRmsCValue": 4.0,
      "vRmsDValue": 7.1,
      "value": [
        {
          "datatype": 0,
          "datatime": 1778661901178,
          "data_category": null,
          "value": [
            {
              "unit": "mm/s",
              "name": "速度有效值",
              "value": 0.8834378123283386
            },
            {
              "unit": "m/s²",
              "name": "加速度峰值",
              "value": 9.086262702941895
            }
          ]
        },
        {
          "datatype": 0,
          "datatime": 1778692187805,
          "data_category": null,
          "value": [
            {
              "unit": "mm/s",
              "name": "速度有效值",
              "value": 0.980688214302063
            },
            {
              "unit": "m/s²",
              "name": "加速度峰值",
              "value": 8.531362533569336
            }
          ]
        }
      ]
    }
  ]
}
```

##### 对接注意事项

- 2K 返回是“三层嵌套”: `data[] -> value[] -> value[]`
- 如果需要和代码中的 `v_rms`, `a_peak` 等字段名对齐, 需要额外做一层中文特征名映射
- 该接口的时间字段为毫秒时间戳, 本次样例时间窗对应 `2026-05-13 15:25:07.824` 到 `2026-05-20 15:25:07.824`

---

### 3. 告警事件

**文件:** `src/api/page.alarm.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/data/getUserAlarmEventList` | GET | 查询用户告警事件列表 | `params: Object` |
| 2 | `/data/getUserAlarmEventCount` | GET | 获取用户告警事件计数 | `params: Object` |
| 3 | `/data/updateUserAlarmEvent` | POST | 更新用户未读告警事件 | `params: Object` |

---

### 4. 事件确认

**文件:** `src/api/page.eventConfirm.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/eventManConfirm/{id}` | GET | 获取事件确认记录 | `id: string` |
| 2 | `/eventManConfirm` | POST | 新增/更新事件确认记录 | `data: Object` (POST body) |

---

### 5. 历史数据

**文件:** `src/api/page.history.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/data/getEqptHisEventList` | GET | 获取设备历史事件列表 | `params: Object` |
| 2 | `/data/getPosidEventByMacId` | GET | 按机器ID获取测点事件 | `params: Object` |

---

### 6. 实时数据

**文件:** `src/api/page.real.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/organize/getEqptOrgPageByType` | GET | 获取设备实时列表数据 | `params: Object` |
| 2 | `/organize/getOrgEquipmentType` | GET | 获取组织节点下设备分类 | `params: Object` |
| 3 | `/organize/getEqptGpInfo` | GET | 查询设备测点结构 | `params: Object` |
| 4 | `/setup/addCommonEqpt` | POST | 收藏设备 | `params: Object` |
| 5 | `/setup/removeCommonEqptById` | POST | 取消收藏设备 | `params: Object` |
| 6 | `/data/getLastTrendData` | POST | 获取最新趋势数据 | `params: Object` |
| 7 | `/data/getPointLastTrendData` | GET | 获取测点最新趋势数据 | `params: Object` |

---

### 7. 运行状态

**文件:** `src/api/page.running.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/static/getDevOperatingStateList` | GET | 获取设备运行状态列表 | `params: Object` |
| 2 | `/excel/static/getDevOperatingXls` | GET | 导出设备运行报表 | `params: Object` (返回blob) |
| 3 | `/static/getEqptOperatingStateList` | GET | 获取设备下机器运行状态 | `params: Object` |

---

### 8. 系统设置

**文件:** `src/api/page.setup.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/setup/getDecideStopMode` | GET | 查询启停自动/手动判断设置 | `params: Object` |
| 2 | `/setup/modifyDecideStopMode` | POST | 修改启停自动/手动判断设置 | `params: Object` |

---

### 9. 6K 静态测厚计划

**文件:** `src/api/page.report.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/sg6kStaticPlan/queryList` | GET | 获取人工测厚计划(年/月) | `params: Object` |
| 2 | `/sg6kStaticPlan/getPlanManualPoints` | GET | 获取执行测点列表 | `params: Object` |
| 3 | `/sg6kStaticPlan/detail` | GET | 获取计划详情 | `params: Object` |
| 4 | `/sg6kStaticPlan/delete` | GET | 删除年度计划 | `params: Object` |
| 5 | `/sg6kStaticPlan/getPlanManualOrgS` | GET | 获取计划详情设备下拉列表 | `params: Object` |
| 6 | `/sg6kStaticPlan/export` | GET | 导出年/月度计划 | `params: Object` |
| 7 | `/sg6kStaticPlan/exportPlanDetail` | GET | 导出计划详情 | `params: Object` (返回blob) |
| 8 | `/sg6kStaticPlan/add` | POST | 新增人工测厚计划 | `data: Object` |
| 9 | `/sg6kStaticPlan/update` | POST | 修改人工测厚计划 | `data: Object` |
| 10 | `/sg6kStaticPlan/updatePoints` | POST | 修改计划中的测点检测周期 | `data: Object` |
| 11 | `/sg6kStaticPlan/updatePlanPointNum` | POST | 更新计划测点数量 | `params: Object` |

---

### 10. 6K 腐蚀/测厚数据

**文件:** `src/api/page.sg6kData.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/sg6kData/getWaveDataHis` | GET | 获取6K波形数据历史 | `params: Object` |
| 2 | `/sg6kData/getValueWithWave` | GET | 获取6K波形特征值 | `params: Object` |
| 3 | `/sg6kData/downloadWaveDataHis` | POST | 下载6K波形数据 | `data: Object` (返回blob) |
| 4 | `/sg6kData/getTrendDataHis` | GET | 6K趋势数据历史 | `params: Object` |
| 5 | `/sg6kData/exportTrendData` | GET | 导出6K趋势数据 | `gpids: string`(JSON序列化) (返回blob) |
| 6 | `/sg6kData/getMachineConf` | GET/POST | 获取机器配置信息 | `params: Object` |
| 7 | `/excel/exportManualInputTemplate` | GET | 导出人工录入模板 | `params: Object` (返回blob) |
| 8 | `/sg6kData/importManualInputData` | POST | 导入单点人工录入数据 | `data: Object` |
| 9 | `/sg6kData/importManualInputDataByOrgId` | POST | 导入多点人工录入数据 | `data: Object` |
| 10 | `/sg6k/delete` | POST | 6K趋势数据批量删除 | `data: Object` |

#### 证据级别: 实测验证（6K，2026-05-20）

##### 请求特征（6K）

- `InsApiClient.get_trend_data(..., endpoint_series="6k")` 路由到 `/ins-os-view/sg6kData/getTrendDataHis`
- 默认查询参数 `gpids`、`startTime`、`endTime`、`density=1`；`factoryId` 仅显式传入时追加（实测加与不加返回完全一致）
- 6K 与 2K 共享 `density=1`，与 8K/9K 的 `density=high` 不同
- 实测命中：`factoryId=449569476879319040`（沈鼓测控/中煤陕西能源化工集团有限公司），`equipmentId=230914010256278`（001#1146LV001 阀组后弯头），`gpid=2309140102562780001`（弯头_TH，`positionType=62`，测厚位），`gpid=2309140102562780002`（弯头_T，`positionType=61`，温度位）

##### 响应结构（6K）

- 顶层 `{code:200, data:[...], msg:"操作成功"}`，`data` 是 list；请求 N 个 `gpids`，响应即 N 条 `data[i]`
- 实测 `data[0]` 键集合：`{endTime, equipmentId, gpid, itemNo, posName, positionType, startTime, value}`（`itemNo` 实测为空串）
- `value` 为外层 list；外层每项含 `datatype`/`datatime` 元数据 + 内层 `value[]` 子 list（实测内层为 `{key, name, unit, value, exportValue}` 字典，`value` 为字符串数字）
- 实测 365 天窗口，`gpid=2309140102562780001`：外层 `value` 长度 = 498，内层样本总数 = 1992，平均每个外层条目展开 4 项（`temperature`/`thickness`/`thinningRate`/`corrosionRate` 等），与 `_ins_provider._KPI_FEATURE_MAP` 的 6K KPI 完全对应
- `gpid=2309140102562780002`（`positionType=61` 温度位）的内层 key 是单值 `"value"`，name `"温度"`，单位 `"℃"`；外层 `value` 长度 = 498，内层 1:1（外层每条对应 1 项 `value`）
- `parse_trend_response(..., "6k")` 把外层 × 内层笛卡尔展开，并按内层 `key` 做字段名（不是 `name`）展平

##### 关键字段（6K）

- `positionType` 取值与字段映射（实测验证）：
  - `61` → 温度（内层 key=`"value"`，name=`"温度"`，unit=`"℃"`）
  - `62` → 测厚（内层 key ∈ {`temperature`, `thickness`, `thinningRate`, `corrosionRate`}，对应 KPI `temperature`/`thickness`/`thinningRate`/`corrosionRate`）
- 实测 `value` 字段类型为字符串（如 `"28.292030334472656"`、`"0.004643144927186203"`），上层 `_ins_provider._aggregate_trend_to_kpi` 会按 KPI 规约（mean/first-minus-last）做聚合
- `datatime`（外层 ms 时间戳）才是采样时间；`startTime` / `endTime`（数据条本身的字段）回显请求窗口
- `posName` 是测点名（如 `"弯头_TH"`、`"弯头_T"`），不是 `name`

##### 对接注意事项（6K）

- 6K 嵌套结构与 2K 相似（外层 `data[] → value[]`），但展平用内层的 `key`（英文）而非中文 `name`
- 6K 采样稀疏：实测在 30 天窗口下 `value=[]`，需放宽到 ~365 天才能稳定拿到样本；上层调度建议月级而非日级
- 服务端可能下发 `value=""`（空串）作为"未上报"占位；`client.py` 会在解析时把空串转 `None`，`_ins_provider` 在 `mean` 聚合时会跳过 `None`，符合 `tests/test_ins_provider_unit.py::test_6k_corrosion_kpis_skip_none_values` 的语义
- `factoryId` 在 6K 趋势接口上是可选的（实测加与不加同结果），但在 `/organize/getOrgTreeByUser` 上 6K 设备只在 `operateType=1` 下才会随机器子树一并返回（`operateType=0` 只返回组织骨架）
- `gpid` 是 19 位数字字符串；`equipmentId` 是 15 位数字字符串；`gpid` 前 15 位即对应 `equipmentId`

---

### 11. 6K 静态报告

**文件:** `src/api/page.sg6kStatic.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/sg6kStaticNew/getSparePartsReportNew` | GET | 获取备品备件报告 | `params: Object` |
| 2 | `/sg6kStaticNew/getMachineReport` | POST | 获取机器统计报告 | `data: Object` |
| 3 | `/sg6kStatic/check/page` | GET | 获取超期/待检测点列表 | `params: Object` |
| 4 | `/sg6kStatic/check/summary/page` | GET | 获取超期/待检汇总表 | `params: Object` |
| 5 | `/sg6kStatic/check/export` | GET | 导出检测点 | `params: Object` (返回blob) |
| 6 | `/sg6kStatic/check/summary/export` | GET | 导出汇总表 | `params: Object` (返回blob) |
| 7 | `/sg6kStaticNew/check/pageNew` | GET | 获取检测点列表(新版) | `params: Object` |
| 8 | `/sg6kStaticNew/check/exportNew` | GET | 导出检测点(新版) | `params: Object` (返回blob) |
| 9 | `/sg6kStaticNew/sparePartsReportExport` | GET | 导出备品备件 | `params: Object` (返回blob) |
| 10 | `/sg6kStaticNew/check/summary/exportNew` | GET | 导出汇总(新版) | `params: Object` (返回blob) |
| 11 | `/sg6kStaticNew/check/summaryNew/page` | GET | 获取汇总表(新版) | `params: Object` |
| 12 | `/sg6kStaticNew/machineReportExport` | POST | 导出机器统计报告 | `data: Object` (返回blob) |
| 13 | `/sg6kStaticNew/getDeviceStatus` | POST | 获取设备实时状态列表 | `orgId, factoryId, deviceName, equipmentName, noPage, type, equipmentType, currentPage, pageSize` |
| 14 | `/sg6kStaticNew/deviceStatusExport` | POST | 导出实时状态列表 | `data: Object` (返回blob) |
| 15 | `/sg6kStaticNew/getManualEntryRecordList` | GET | 获取人工测厚数据审核列表 | `params: Object` |
| 16 | `/sg6kStaticNew/exportManualEntryRecordList` | GET | 导出审核列表 | `params: Object` (返回blob) |
| 17 | `/sg6kStaticNew/getPointInfoByCraftBit` | GET | 按工艺位号查询测点信息 | `craftBit: string`, `factoryId: string` |
| 18 | `/sg6kStaticNew/getManualEntryModelByRecordId` | GET | 获取数据录入模板 | `recordId: string` |
| 19 | `/sg6kStaticNew/getUserManualEntryTemplateList` | GET | 获取数据录入模板列表 | `params: Object` |
| 20 | `/sg6kStaticNew/saveManualEntryAsModel` | POST | 保存人工录入为模板 | `thicknessDataList, modalName, factoryId` |
| 21 | `/sg6kStaticNew/deleteManualEntryModelByRecordId` | DELETE | 删除人工录入模板 | `recordId: string` |
| 22 | `/sg6kStaticNew/commitOrUpDateManualEntryDataRecord` | POST | 提交人工测厚录入数据 | `thicknessDataList, factoryId` |
| 23 | `/sg6kStaticNew/manDataCalculation/task/submit` | POST | 提交人工数据计算任务 | `data: Object` |
| 24 | `/sg6kStaticNew/importManualInputData` | POST | 导入人工录入数据 | `formData: FormData` |
| 25 | `/sg6kStaticNew/changeManualEntryRecordStatus` | GET | 修改审核状态 | `factoryId, status(1=通过,2=驳回), recordId` |
| 26 | `/sg6kStaticNew/getManualEntryDataByRecordId` | GET | 获取已提交人工测厚数据 | `params: Object` |
| 27 | `/sg6kStaticNew/getManualEntryStatus` | GET | 获取人工测厚实时报告 | `params: Object` |
| 28 | `/sg6kStaticNew/manualEntryStatusExport` | GET | 导出人工测厚实时列表 | `params: Object` (返回blob) |
| 29 | `/sg6kStaticNew/saveManualEntryStatusQuery` | GET | 保存查询条件 | `params: Object` |
| 30 | `/sg6kStaticNew/getManualEntryStatusQueryList` | GET | 获取已存查询模板列表 | `params: Object` |
| 31 | `/sg6kStaticNew/deleteManualEntryStatusQueryTemplate` | DELETE | 删除查询模板 | `queryTemplateId: string` |
| 32 | `/sg6kStaticNew/machineList` | GET | 查询设备设置列表 | `params: Object` |
| 33 | `/sg6kStaticNew/batchEditConfigInfo` | GET | 批量设置测点配置 | `orgId, keyword, uploadCycle, lastDataTimeStart/End, minCorrosionRate, maxCorrosionRate, minThickness, maxThickness, configInfo` |
| 34 | `/sg6kStaticNew/equipmentAttributeList` | POST | 获取设备属性列表 | `orgId, userId, type, pipelineLevels, classifications, safetyCondition, search, pressureVesselCategorys, pageInfo` |
| 35 | `/sg6kStaticNew/exportEquipmentAttributeList` | POST | 导出设备属性列表 | `data: Object` (返回blob) |
| 36 | `/sg6kStaticNew/getStaReport/day` | GET | 获取日报过程报告 | `params: Object` |
| 37 | `/sg6kStaticNew/staReportExport/day` | POST | 导出日报 | `params: Object` (返回blob) |
| 38 | `/sg6kStaticNew/getStaReport/month/up` | GET | 获取月报(上半部分) | `params: Object` |
| 39 | `/sg6kStaticNew/getStaReport/month/down` | GET | 获取月报(下半部分) | `params: Object` |
| 40 | `/sg6kStaticNew/staReportExport/month` | POST | 导出月报 | `params: Object` (返回blob) |
| 41 | `/sg6kStaticNew/exportManualInputTemplateByOrgIdNew` | GET | 下载人工录入模板 | `params: Object` (返回blob) |
| 42 | `/sg6k/strength/queryList` | GET | 强度校验查询列表 | `params: Object` |
| 43 | `/sg6k/strength/getParam` | GET | 获取强度校验参数 | `params: Object` |
| 44 | `/sg6k/strength/saveResult` | POST | 保存强度校验结果 | `data: Object` |
| 45 | `/sg6k/strength/saveRemark` | POST | 保存强度校验备注 | `data: Object` |
| 46 | `/sg6k/strength/excel` | GET | 导出强度校验列表 | `params: Object` (返回blob) |
| 47 | `/sg6kStaticNew/temperature/queryList` | GET | 温度波动报告查询 | `params: Object` |
| 48 | `/sg6kStaticNew/temperature/export` | POST | 导出温度波动报告 | `params: Object` (返回blob) |
| 49 | `/setup/updateUserView` | POST | 编辑用户视图 | `data: Object` |
| 50 | `/setup/addUserView` | POST | 新增用户视图 | `data: Object` |
| 51 | `/setup/deleteUserView` | DELETE | 删除用户视图 | `params: Object` |
| 52 | `/setup/updateUserDefaultView` | POST | 设置默认用户视图 | `data: Object` |

---

### 12. 7K 静态设备

**文件:** `src/api/page.sg7kStatic.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/sg7kStatic/getMachineReport` | GET | 获取7K机器报告 | `params: Object` |

---

### 13. 8K 大型旋转机械数据

**文件:** `src/api/page.sg8kData.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/sg8kData/getTrendDataHis` | GET | 获取bode/轴心轨迹等历史数据 | `params, cancelToken` |
| 2 | `/sg8kData/getMachineColorBand` | GET | 获取机器色带(时间轴状态) | `params: Object` |
| 3 | `/sg8kData/getValueWithWave` | GET | 获取带波形的特征值 | `params: Object` |
| 4 | `/sg8kData/getTrendDataRT` | GET | bode/轴心轨迹实时数据 | `params: Object` |
| 5 | `/sg8kData/getMachineSSList` | GET | 获取机器启停列表 | `machineId, startTime, endTime` |
| 6 | `/sg8kData/getMachineConf` | POST | 获取机器配置 | `data: Object` |
| 7 | `/sg8kData/getWaveDataHis` | GET | 获取波形数据历史 | `params: Object` |
| 8 | `/sg8kData/getWaveDataHisList` | GET | 获取波形历史列表(单点多时间) | `params: Object` |
| 9 | `/sg8kData/getWaveIndexList` | GET | 获取波形数据时间索引列表 | `gpids, startTime, endTime, density, includeFilter, currentPage, pageSize, noPage` |
| 10 | `/sg8kData/getWaveDataRT` | GET | 获取实时波形数据 | `params: Object` |
| 11 | `/sg8kData/editKeyPointTime` | GET | 设置键相点采样时长 | `gpid, time` |
| 12 | `/sg8kData/getMachineDrops` | GET | 获取机器水滴(事件标记) | `startTime, endTime, macId, type(1=主报警,2=预报警,3=启停,4=黑匣子等), pointId?` |

#### 证据级别: 实测验证（8K，2026-05-20）

##### 请求特征（8K）

- 趋势接口由 `InsApiClient.get_trend_data(..., endpoint_series="8k")` 调用到 `/ins-os-view/sg8kData/getTrendDataHis`
- 必备参数是 `gpids`, `startTime`, `endTime`
- 8K 默认补齐 `density=high`, `includeFilter=history,startstop,blackbox,alarm`, `typeList=<逗号拼接 features>`
- `factoryId` 仅在显式传入时追加，不会无条件注入
- 本次实测使用 `factoryId=217321543372374016`、单个 8K 振动测点 `gpid=2108190944456560007` 命中

##### 响应结构（8K）

- 客户端按 8K/9K 共用逻辑走 `parse_trend_response_multi(...)`
- 真实响应顶层为 `{ code: 200, data: [...], msg }`，`data` 是 `list`
- 实测 `data[0]` 的键集合为 `{dataArr, gpid, typeList, startTime, endTime}`
- 单点单日窗口下，`dataArr` 长度可达 ~3300（实测 `len(dataArr)=3305`），`typeList` 长度与请求 `typeList` 项数一致（实测 5 项）
- `parse_trend_response_multi` 会把 `dataArr` 与 `typeList` 笛卡尔展开，单元一致地归一成 `{ component_id, time_ms, time, values }`
- `values` 中的典型字段包括 `pp_value`, `temperature`, `flow`, `pressure`, `speed`

##### 关键字段（8K）

- 8K 点位判定以 `positionType 81..83` 为主，其中 `83` 为振动点，`82` 常承载过程量
- `_ins_provider` 当前直接消费的 8K KPI 特征包括 `pp_value`, `temperature`, `flow`, `pressure`, `speed`
- 告警计数依赖点位配置里的 `h_alarm` / `hh_alarm`

##### 对接注意事项（8K）

- 8K 趋势接口不是 2K/6K 那种嵌套 `value[]` 结构，客户端不会再做中文名或 `key` 展平
- 波形/轴心轨迹能力复用 8K `getWaveDataHis`，客户端会解码 `waveStr`，并在轨迹场景中按 `type_num=83` 搜索轴振探头
- `typeList` 的取值应与所需特征字段保持一致，否则会出现响应有时间点但 `values` 缺列的情况
- 服务端可能按权限/采集状态裁剪 `typeList`：实测请求 5 项 typeList 时服务端按原样返回；但 9K 同名接口出现过请求 4 项、响应 3 项的情况（详见 9K 小节），上层在按 typeList 拉特征时需做长度自适应

---

### 14. 8K 事件

**文件:** `src/api/page.sg8kEvent.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/sg8kEvent/getMachineStatusRT` | GET | 获取机器实时状态 | `machineIds, isRetOffLine(0/1)` |
| 2 | `/sg8kEvent/getMachineEventHisList` | GET | 获取机器事件历史列表 | `machineIds, type, startTime, endTime` |
| 3 | `/sg8kEvent/getLastMachineSSItem` | GET | 获取最近启停项 | `params: Object` |
| 4 | `/sg8kEvent/getMachineEventComments` | GET | 查询事件评论 | `params: Object` |
| 5 | `/sg8kEvent/addMachineEventComment` | GET | 添加事件评论 | `params: Object` |
| 6 | `/sg8kEvent/delMachineEventComment` | GET | 删除事件评论 | `params: Object` |

---

### 15. 8K 润滑油报告

**文件:** `src/api/page.sg8kLube.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/lube/getLubeManual` | GET | 查询润滑油产品手册 | `params: Object` |
| 2 | `/lube/getLubeReport` | GET | 查询综合分析评价报告 | `params: Object` |
| 3 | `/lube/getSwitchLubeInfo` | GET | 查询设备换油信息表 | `params: Object` |
| 4 | `/lube/addSwitchLubeInfo` | GET | 添加设备换油信息 | `params: Object` |
| 5 | `/lube/getLastChangeInfo` | GET | 获取最新换油信息 | `params: Object` |
| 6 | `/lube/lubeManualExport` | GET | 导出润滑油手册 | `params: Object` (返回blob) |
| 7 | `/lube/lubeReportExport` | GET | 导出润滑油报告 | `params: Object` (返回blob) |
| 8 | `/lube/lubeSwitchExport` | GET | 导出换油信息 | `params: Object` (返回blob) |

---

### 16. 9K 往复机械数据

**文件:** `src/api/page.sg9kData.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/organize/getEqptOrgPageByType` | GET | 获取9K实时状态列表 | `orgId, factoryId, equipmentType` |
| 2 | `/sg9kData/getMachineConf` | GET | 获取9K测点配置 | `params: Object` |
| 3 | `/sg9kData/getWaveIndexList` | GET | 获取波形数据时间索引列表 | `params: Object` |
| 4 | `/sg9kData/getWaveDataHis` | GET | 获取波形数据历史 | `params: Object` |
| 5 | `/sg9kData/getTrendDataHis` | GET | 9K趋势数据历史 | `params: Object` |
| 6 | `/sg9kData/getMachineSSList` | GET | 获取机器启停列表 | `params: Object` |
| 7 | `/sg9kData/getMachineMaxValue9k` | GET | 获取9K机器最大振动值 | `params: Object` |
| 8 | `/sg9kData/getValueWithWave` | GET | 获取带波形的特征值 | `params: Object` |
| 9 | `/sg9kData/getIndicatorInfoHis` | GET | 获取子设备历史指标信息(PV图/活塞杆力) | `componentId, dataTime, curveType(1=pv, 2=force)` |
| 10 | `/sg9kData/getIndicatorInfoRT` | POST | 获取子设备实时指标信息 | `componentId, curveType, pointInfoArr` |
| 11 | `/sg9kData/getTrendDataByMachineIdAndTime` | GET | 按机器和时间获取趋势分析数据 | `params: Object` |
| 12 | `/data/getDiagEventList9k` | GET | 获取9K智能诊断事件列表 | `factoryId, startTime, endTime, machineIds, diagType, noPage, currentPage, pageSize` |
| 13 | `/sg9kData/getMachineDrops` | GET | 获取9K机器水滴(事件标记) | `params: Object` |
| 14 | `/sg9kData/getMachineColorBand` | GET | 获取机器色带(时间轴) | `params: Object` |

#### 证据级别: 实测验证（9K，2026-05-20）

##### 请求特征（9K）

- 趋势接口由 `InsApiClient.get_trend_data(..., endpoint_series="9k")` 路由到 `/ins-os-view/sg9kData/getTrendDataHis`
- 必备参数是 `gpids`, `startTime`, `endTime`
- 9K 默认补齐 `density=high`, `includeFilter=history`, `typeList=<逗号拼接 features>`
- `factoryId` 仍然是可选透传参数，不传就不会出现在查询串中
- 本次实测使用 `factoryId=534385048091099136`、9K 测点 `gpid=2401151011100860017` 命中

##### 响应结构（9K）

- 9K 与 8K 共用 `parse_trend_response_multi(...)`，按 `component_id + time_ms` 聚合每个时间点的多特征值
- 真实响应顶层为 `{ code: 200, data: [...], msg }`，`data` 是 `list`
- 实测 `data[0]` 的键集合与 8K 一致：`{dataArr, gpid, typeList, startTime, endTime}`
- 单点单日窗口下，`dataArr` 长度约为千级（实测 `len(dataArr)=1911`）
- 客户端视角下，9K 会被统一成 `{ component_id, time_ms, time, values }`

##### 关键字段（9K）

- spec 中把 `positionType 91..99` 归到 9K 点位族，覆盖机身振动、十字头振动、活塞杆偏摆、盖侧/轴侧压力、键相、过程量等
- 9K 专有页面还额外暴露 `getIndicatorInfoHis` / `getIndicatorInfoRT`，用于 PV 图和活塞杆力曲线
- 组织树扫描中，本站 8 个工厂的 `type=9` 设备总数为 63，分布远稀于 `type=4`（779 台）和 `type=1`（51 台）

##### 对接注意事项（9K）

- 9K 和 8K 虽然都走"扁平时间序列"解析，但默认 `includeFilter` 不同：9K 只补 `history`，8K 额外包含 `startstop,blackbox,alarm`
- 实测中观察到服务端会按权限/采集状态裁剪 `typeList`：请求 4 项特征时，响应中 `data[0].typeList` 只有 3 项；上层在按 typeList 解析 `dataArr` 时必须用**响应 `typeList`** 的长度，而不是请求 `typeList` 的长度
- 当前仓库缺少 9K 前端源码，`curveType`、`pointInfoArr` 等业务字段仅能保留接口表含义，不能扩写为确定的请求体结构
- 若后续要验证 `getIndicatorInfoHis`，需要先拿到 9K 子设备的 `componentId`（可通过 `/ins-os-manage/organize/getComponentByMachineIds?operateType=1&machineIds=…` 获取，已实测）

---

### 17. 9K 事件

**文件:** `src/api/page.sg9kEvent.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/sg9kEvent/getMachineStatusRT` | GET | 获取9K机器实时状态 | `params: Object` |
| 2 | `/sg8kEvent/getMachineEventHisList` | GET | 获取机器事件历史列表(复用8K接口) | `params: Object` |
| 3 | `/sg8kEvent/getLastMachineSSItem` | GET | 获取最近启停项(复用8K接口) | `params: Object` |
| 4 | `/sg8kEvent/getMachineEventComments` | GET | 查询事件评论(复用8K接口) | `params: Object` |
| 5 | `/sg8kEvent/addMachineEventComment` | GET | 添加事件评论(复用8K接口) | `params: Object` |
| 6 | `/sg8kEvent/delMachineEventComment` | GET | 删除事件评论(复用8K接口) | `params: Object` |

---

### 18. 通用事件评论

**文件:** `src/api/page.sgComment.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/sg{machineFrom}Event/getMachineEventComments` | GET | 通用评论查询 | `params, machineFrom(8k/9k)` |
| 2 | `/sg{machineFrom}Event/addMachineEventComment` | GET | 通用添加评论 | `params, machineFrom(8k/9k)` |
| 3 | `/sg{machineFrom}Event/delMachineEventComment` | GET | 通用删除评论 | `params, machineFrom(8k/9k)` |

---

### 19. 诊断事件与报告工具

**文件:** `src/api/page.tools.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/bearingLibrary/list` | GET | 轴承库查询 | `query: Object` |
| 2 | `/bearingLibrary/listBearingUnderMachine` | GET | 查询机器下轴承列表 | `query: Object` |
| 3 | `/diagEvent/listPublic` | POST | 公共诊断事件分页查询 | `currentPage, pageSize, pageFlag, orderFieldList, keyWord, faultTimeStartMS, faultTimeEndMS, orgId, machineId, subjectType, diagEventType, handleStep, verifyState, createType, malfunctionType, malfunctionSubType, diagType, eventSubType, eventHappenType` |
| 4 | `/diagEvent/list` | POST | 诊断事件列表查询 | 同 listPublic |
| 5 | `/excel/diagEventExcel/exportDataDiagEvent` | POST | 导出诊断事件 | `query: Object` (返回blob) |
| 6 | `/diagEventRemark/list` | POST | 查询诊断事件评论列表 | `query: Object` |
| 7 | `/diagEventRemark/addInfo` | POST | 添加诊断事件评论 | `operator, remarkSource, createTime, diagEventId, createUserId, remarkUserName, remarkInfo, imageArr, sceneReportType, id, parentId, createUserWechatId` |
| 8 | `/diagEventRemark/updateInfo` | POST | 编辑诊断事件评论 | `query: Object` |
| 9 | `/diagEventRemark/removeInfo` | POST | 删除诊断事件评论 | `query: Object` |
| 10 | `/fileCommon/getImageUploadUrl` | POST | 获取OSS图片上传URL | `query: Object` |
| 11 | `/diagEvent/updateClientView` | POST | 编辑客户端可见状态 | `id, clientViewState(0/1)` |
| 12 | `/diagEventLog/list` | POST | 获取诊断事件操作日志 | `query: Object` |
| 13 | `/diagEventMessage/publish` | POST | 发布/推送诊断事件 | `eventId, targetIds` |
| 14 | `/diagEventMessage/getNoticeTargetInfoByEventId` | GET | 按事件ID获取推送目标 | `params: Object` |
| 15 | `/diagEvent/removeList` | POST | 删除诊断事件 | `idList` |
| 16 | `/diagEvent/listSimple` | POST | 获取诊断事件简单列表(关联重复事件用) | `query: Object` |
| 17 | `/diagEvent/detail` | POST | 获取诊断事件详情 | `id` |
| 18 | `/diagEvent/addInfo` | POST | 新增诊断事件记录 | `query: Object` |
| 19 | `/diagEvent/updateToSystem` | POST | 分析事件转为系统事件 | `query: Object` |
| 20 | `/diagEvent/updateInfo` | POST | 编辑诊断事件记录 | `query: Object` |
| 21 | `/excel/exportMachineDataHisListPost` | POST | 导出机器数据历史列表 | `factoryId, machineId, gpids, typeList, startTime, endTime, includeFilter, density` (返回arraybuffer) |
| 22 | `/report/list` | POST | 获取分析报告列表 | `orgId, timeStart, timeEnd, name, macTypes, types, formats, pageInfo` |
| 23 | `/fileCommon/download/url/{fileId}/lastVersion` | POST | 获取文件下载URL(最新版本) | `fileId: string` |
| 24 | `/generalCaseLibrary` | GET | 通用案例库查询 | `query: Object` |
| 25 | `/setup/addUserView` | POST | 添加用户视图 | `data: Object` |
| 26 | `/setup/updateUserView` | POST | 更新用户视图 | `data: Object` |
| 27 | `/setup/deleteUserView` | DELETE | 删除用户视图 | `params: Object` |
| 28 | `/setup/updateUserDefaultView` | POST | 设置默认用户视图 | `data: Object` |

---

### 20. 专家库

**文件:** `src/api/page.tools.expert.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/expert/query` | GET | 专家分页查询 | `currentPage, pageSize, name?, serviceContent?, qualification?` |
| 2 | `/expert/preview` | GET | 专家文件预览 | `id: string` (返回arraybuffer) |

---

### 21. 工作流/审批

**文件:** `src/api/page.workflow.js`

所有接口均标记 `dontNeedFactory: true`（不自动注入 factoryId）

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/flow/statistics` | GET | 工作流待办/已办统计 | `params: Object` |
| 2 | `/flow/query` | GET | 流程查询(通用) | `params: Object` |
| 3 | `/flow/export` | GET | 流程导出 | `params: Object` (返回文件) |
| 4 | `/flow/look` | GET | 查看流程详情(仅人工测厚) | `params: Object` |
| 5 | `/flow/chart` | GET | 从流程进入趋势图 | `params: Object` |
| 6 | `/flow/pass` | POST | 审批通过 | `data: Object` |
| 7 | `/flow/save` | POST | 保存/暂存流程 | `data: Object` |
| 8 | `/flow/next` | POST | 转审/转交流程 | `data: Object` |
| 9 | `/flow/back` | POST | 退回/驳回流程 | `data: Object` |
| 10 | `/flow/user/selectByName` | GET | 模糊搜索授权用户 | `params: Object` |
| 11 | `/flow/submitAgain` | POST | 重新提交流程 | `data: Object` |
| 12 | `/sg6kStaticNew/saveManualEntryDataRecordForFlow` | POST | 提交人工测厚数据(工作流专用,无鉴权) | `data: Object` |
| 13 | `/sg6kStaticNew/getPointInfoByCraftBit` | GET | 按工艺位号查询测点(工作流版本) | `params: Object` |

---

### 22. 设备设置与组织结构

**文件:** `src/api/set.eqpt.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/organize/getOrgTreeByUser` | GET | 按用户权限获取导航树 | `operateType(0=无设备)` |
| 2 | `/organize/getComponentByEqptIds` | GET | 按设备ID获取组件结构 | `params: Object` |
| 3 | `/data/getUserFirstPosInfo` | GET | 获取用户默认首页测点 | `params: Object` |
| 4 | `/setup/editEquipmentParam` | POST | 编辑设备参数 | `params: Object` |
| 5 | `/setup/updatePictureInfo` | POST | 新增/更新图片 | `params: Object` |
| 6 | `/setup/removePicture` | POST | 删除图片 | `params: Object` |
| 7 | `/data/getPictureByEquipmentId` | GET | 获取设备下所有图片 | `params: Object` |
| 8 | `/data/getEqptInfoById` | GET | 获取设备详细信息 | `params: Object` |
| 9 | `/paramModel/list` | GET | 查询设备设置参数模板 | `params: Object` |
| 10 | `/paramInfo/query` | GET | 获取设备参数信息 | `params: Object` |
| 11 | `/machine/listMachineByOrgIdAndType` | GET | 按组织ID和类型获取设备列表 | `params: Object` |
| 12 | `/component/listCompByMacIds` | GET | 按机器ID获取组件列表 | `params: Object` |
| 13 | `/device/listByPointId` | GET | 按测点/机器/组织获取采集器列表 | `pointId?, machineId?, orgId?` |
| 14 | `/machine/queryMachineListByDeviceId` | GET | 按采集器/传感器ID获取设备列表 | `params: Object` |
| 15 | `/machine/getMacForOverView` | GET | 获取机器名称/路径/类型 | `params: Object` |
| 16 | `/paramModel/getParamModelClassification` | GET | 获取6K参数模板分类ID | `params: Object` |
| 17 | `/machine/getSg6kSubMacType` | GET | 获取设备子分类 | `params: Object` |
| 18 | `/component/getSg6kComponentSubType` | GET | 获取组件子分类 | `macSubType: number` |
| 19 | `/damageEntry/listByComponentId` | GET | 查询组件下损伤信息 | `params: Object` |
| 20 | `/damageEntry/getDamageCategory` | GET | 获取损伤类别 | `params: Object` |
| 21 | `/damageEntry/getDamageFactor` | GET | 获取损伤因素 | `damageCategoryCode: string` |

#### 证据级别: 实测验证（22. 设备设置与组织结构，2026-05-20）

- 这一组接口主要承担设备/组件/测点的配置与树形筛选，适合和 `ui-view` 的组织树、组件树、设备详情联动理解。
- `operateType=0` 的导航树只保留无设备结构，和设备设置页的树选择器语义一致。
- `device/listByPointId` 支持按测点、设备、组织三种入口回溯采集器，说明这组接口在前端承担的是"从树到设备再到采集器"的配置链路。

##### `/ins-os-view/organize/getOrgTreeByUser`（实测）

- 必备查询参数：`factoryId`（必填）、`operateType`（`0` 仅返回组织节点，不展开设备；`1` 同步返回 `overviewCount`/告警等总览字段）
- 实测响应顶层结构为 `{ code: 200, data: [...], msg }`，`data[0]` 为根组织节点
- `operateType=0` 时，节点键集合实测为：`{path, hiddenFlag, children, displayOrder, id, type, authFlag, syncSourceId, parentId, name}`
- `operateType=1` 时在上述键之外追加 `overviewCount` 等总览字段
- 节点的 `type` 字段映射到设备类别：`1`=8K、`4`=2K（占多数）、`6`=6K、`9`=9K；本次实测扫描 8 个工厂得到 `type=1 共 51 台 / type=4 共 779 台 / type=6 共 0 台 / type=9 共 63 台`
- 当前项目并未直接转发该接口，而是在网关暴露了 `GET /api/organize/tree`（见下条）

##### `GET /api/organize/tree`（当前项目网关代理，代码验证）

- 入口由 `backend/app/gateway/routers/organize.py` 处理，再通过 `backend/packages/harness/deerflow/rpc/organize_service.py` 转发到下游 `ins-bus-rpc/organize/getOrgTreeByUserIdAndOrgId`
- 当前项目已验证的查询参数：`userId?`、`orgId`、`treeType`、`content?`、`hiddenIfValid?`、`ifAddOverviewCount?`、`viewId?`、`typeId?`
- `userId` 省略时优先取认证上下文中的用户 ID；若仍不可用，网关会回退到 `1`
- RPC 返回若是 `{ code, msg, data }` 包装结构，客户端会自动解包出 `data` 列表

##### `/ins-os-manage/organize/getComponentByMachineIds`（实测）

- 必备查询参数：`operateType=1`、`machineIds=<逗号分隔机器ID>`
- 实测响应每个机器节点会带出子组件树，节点键实测包括 `{children, configInfo, craftBit, id, name, subclass, type, unitType, machineId, parentId, shaftName}`，并在叶子上携带告警阈值
- 该接口是 9K/8K 子组件（`componentId`）→ 测点（`gpid`）映射的唯一稳定来源；对接 `getIndicatorInfoHis`、`getMachineConf` 前应先拿这里返回的 `componentId`

---

### 23. 数据字典

**文件:** `src/api/sys.dict.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/dataDict/types/datas?dictTypes={data}` | GET | 批量获取字典数据 | `data: string`(逗号分隔) |
| 2 | `/dataDict/types/{dictType}/datas` | GET | 按类型获取字典详情 | `dictType: string` |

---

### 24. 组织查询

**文件:** `src/api/sys.organize.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/organize/getEqptListByName` | GET | 模糊搜索设备列表 | `params: Object` |
| 3 | `/organize/getEqptGpInfo` | GET | 查询设备测点结构 | `params: Object` |
| 4 | `/organize/getPointInfosByMachineIds` | GET | 获取设备下所有测点 | `params: Object` |
| 5 | `/data/getPointEnableConfig` | GET | 获取测点MQTT主题 | `params: Object` |

#### 证据级别: 仅文档整理（组织查询）

- 这一组接口与 `ui-view` 的设备树、测点树和设备检索是同一类能力，核心是从组织/设备定位到测点，再反查测点详情或主题配置。
- `getEqptListByName`、`getEqptGpInfo`、`getPointInfosByMachineIds` 形成了"名称搜索 → 设备结构 → 测点明细"的典型查询链路。
- `getPointEnableConfig` 明确指向测点启用后的 MQTT 主题配置，属于设备联调与采集配置的辅助接口。

#### 对接提醒（当前项目）

- 如果目的是在 DeerFlow 当前后端里复用组织树能力，应优先对接 `GET /api/organize/tree`（详见 22 节"实测验证"小节），而不是继续假设前端直连旧的 `/organize/*` 接口族。
- 旧文档中的 `/organize/getEqptListByName`、`/organize/getEqptGpInfo`、`/organize/getPointInfosByMachineIds` 仍适合做 InS 原始能力盘点，但它们目前没有在本仓库中找到与 `/api/organize/tree` 同等级的后端代理实现证据。
- 如果只是想拿到机器到组件/测点的映射，应直接对接 22 节里实测验证过的 `/ins-os-manage/organize/getComponentByMachineIds`，比 `getPointInfosByMachineIds` 含义更明确，且会带出告警阈值。

---

### 25. 8K 组织管理

**文件:** `src/api/sys.sg8kOrganize.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/sg8kOrganize/transferMacToIns` | POST | 迁移单台SG8000机器到InS OS | `params: Object` |
| 2 | `/sg8kOrganize/transferAllMacToIns` | POST | 迁移全部SG8000机器到InS OS | `params: Object` |
| 3 | `/organize/getMachineStruct` | GET | 按组件/测点ID获取机器组织结构 | `params: Object` |
| 4 | `/organize/getCommonPath` | GET | 获取最长公共路径 | `idAndType: string`(JSON序列化) |
| 5 | `/organize/getMacPath` | GET | 获取设备完整路径 | `params: Object` |

---

### 26. 融智第三方认证

**文件:** `src/api/rz.authority.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/rong-zhi/auth/login` | GET | 融智第三方登录 | `params: Object` |
| 2 | `/rong-zhi/auth/getMacInfo` | GET | 获取融智机器信息 | `params: Object` |

---

### 27. 外部直调接口

| # | URL | 方法 | 功能说明 | 入参 |
|---|-----|------|---------|------|
| 1 | `https://ai.shenguyun.com/v1/workflows/run` | POST | AI趋势分析(流式) | `{inputs, response_mode:'streaming', user}`, 认证: Bearer Token |
| 2 | `https://ai.shenguyun.com/v1/files/upload` | POST | 上传截图到AI分析 | FormData(`file`, `user`), 认证: Bearer Token |
| 3 | 动态URL(BaseWaveRequest) | POST | 瀑布图波形数据 | `Content-Type: application/x-www-form-urlencoded`, 返回arraybuffer |
| 4 | OSS动态URL | PUT | 上传图片到OSS | 文件blob |

---

# 二、ui-manage (系统管理端)

## 架构概览

| 项目 | 说明 |
|------|------|
| 基础路径 | `window.baseURL` (解析为 `/ins-os-manage`) |
| 离线数据路径 | `/ins-os-offlinedata` |
| HTTP 库 | Axios（2个实例） |
| 认证方式 | Bearer JWT Token (Cookie中获取)，自动刷新 |
| 刷新端点 | `GET /refresh` |

---

### 1. 认证登录

**文件:** `src/api/login.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/loginN` | POST | 加密凭证登录 | `enCodeUser: string`, `enCodePassword: string`, `captcha: string`, `validation: string` |
| 2 | `/captcha` | GET | 获取验证码 | 无 |
| 3 | `/getInfo` | GET | 获取当前用户详情/角色/权限/路由 | `data?: Object` (如 `{rxVersion: 1}`) |
| 4 | `/logout` | POST | 注销登录 | 无 |

---

### 2. 用户管理

**文件:** `src/api/system/user.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/user/getUserListWithDataScope` | GET | 获取含数据权限的用户列表 | 无 |
| 2 | `/user/list` | GET | 查询用户列表(分页) | `query: Object` |
| 3 | `/user/query` | GET | 按ID查用户详情 | `data: Object` |
| 4 | `/user/add` | POST | 新增用户 | `data: Object` (body) |
| 5 | `/user/edit` | POST | 编辑用户 | `data: Object` (body) |
| 6 | `/user/editBatch` | POST | 批量更新用户 | `data: Object` (body) |
| 7 | `/user/remove` | POST | 删除用户 | `data: Object` (params) |
| 8 | `/user/resetPwd` | POST | 管理员重置用户密码 | `data: Object` (params) |
| 9 | `/user/checkPasswordReset` | GET | 检查是否需要修改密码 | 无 |
| 10 | `/system/user/export` | GET | 导出用户列表 | `query: Object` |
| 11 | `/user/editStatus` | POST | 启用/禁用用户 | `userId: number`, `status: string` (params) |
| 12 | `/system/user/profile` | GET | 获取当前用户个人信息 | 无 |
| 13 | `/updateInfo` | POST | 更新用户个人信息 | `data: Object` (body) |
| 14 | `/updatePwd` | POST | 修改当前用户密码 | `oldPassword: string`, `newPassword: string` (params) |
| 15 | `/system/user/importTemplate` | GET | 下载用户导入模板 | 无 |
| 16 | `/user/editDataScope` | POST | 修改用户数据权限范围 | `data: Object` (params) |
| 17 | `/user/import` | POST | 批量导入用户 | `data: FormData` (body, 60s超时) |
| 18 | `/user/queryUserRule` | POST | 查询用户列表查询规则 | `data: Object` (params) |
| 19 | `/user/editUserRule` | POST | 添加/更新用户查询规则 | `data: Object` (params) |

---

### 3. 组织管理

**文件:** `src/api/system/dept.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/org/getOrgAllList` | GET | 获取所有组织列表 | 无 |
| 2 | `/org/selectTree` | GET | 按父级ID查询组织树 | `parentId: string/number` |
| 3 | `/org/objTree` | GET | 查询组织树列表 | `query: Object` |
| 4 | `/org/objList` | GET | 模糊搜索组织列表 | `query: Object` |
| 5 | `/system/dept/roleDeptTreeselect/{roleId}` | GET | 按角色ID查组织树 | `roleId: string` |
| 6 | `/org/add` | POST | 新增组织 | `data: Object` (body) |
| 7 | `/org/edit` | POST | 编辑组织 | `data: Object` (body) |
| 8 | `/org/remove` | POST | 删除组织 | `data: Object` (params) |
| 9 | `/org/addOrgSync` | POST | 添加组织同步关系 | `data: Object` (params) |
| 10 | `/org/getOrgSync` | GET | 获取组织同步关系 | `data: Object` (params) |
| 11 | `/org/executeSync` | POST | 执行组织同步 | `data: Object` (params) |
| 12 | `/org/delOrgSync` | POST | 删除组织同步关系 | `data: Object` (params) |
| 13 | `/org/sort` | POST | 组织排序 | `data: Object` (params) |
| 14 | `/org/getComponentTreeByOrgId` | GET | 按orgId获取右侧导航树 | `data: Object` (params) |
| 15 | `/org/setHiddenFlag` | POST | 设置设备/区域/组件/测点隐藏标记 | `data: Object` (body) |

---

### 4. 角色管理

**文件:** `src/api/system/role.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/role/list` | GET | 查询角色列表 | `query: Object` |
| 2 | `/role/orgRoles` | GET | 按组织查询角色 | `query: Object` |
| 3 | `/role/query` | GET | 查询角色详情 | `data: Object` |
| 4 | `/role/add` | POST | 新增角色 | `data: Object` (body) |
| 5 | `/role/edit` | POST | 编辑角色 | `data: Object` (body) |
| 6 | `/system/role/dataScope` | PUT | 设置角色数据权限范围 | `data: Object` (body) |
| 7 | `/role/editStatus` | POST | 启用/禁用角色 | `roleId: number`, `status: string` (params) |
| 8 | `/role/remove` | POST | 删除角色 | `data: Object` (params) |
| 9 | `/system/role/export` | GET | 导出角色列表 | `query: Object` |
| 10 | `/user/queryUserListByRoleId` | GET | 查询角色关联用户 | `params: Object` |
| 11 | `/role/deleteUserRoleByUserIds` | POST | 删除用户-角色绑定 | `data: Object` (body) |

---

### 5. 菜单管理

**文件:** `src/api/system/menu.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/menu/list` | GET | 查询菜单列表 | `query: Object` |
| 2 | `/system/menu/{menuId}` | GET | 查询菜单详情 | `menuId: number` |
| 3 | `/menu/selectTree` | GET | 获取菜单下拉树 | 无 |
| 4 | `/system/menu/roleMenuTreeselect/{roleId}` | GET | 按角色获取菜单树 | `roleId: number` |
| 5 | `/system/menu` | POST | 新增菜单 | `data: Object` (body) |
| 6 | `/system/menu` | PUT | 更新菜单 | `data: Object` (body) |
| 7 | `/system/menu/{menuId}` | DELETE | 删除菜单 | `menuId: number` |

---

### 6. 系统配置

**文件:** `src/api/system/config.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/system/config/list` | GET | 查询配置参数列表 | `query: Object` |
| 2 | `/system/config/{configId}` | GET | 按ID查询配置详情 | `configId: number` |
| 3 | `/system/config/configKey/{configKey}` | GET | 按Key名查询配置 | `configKey: string` |
| 4 | `/system/config` | POST | 新增配置参数 | `data: Object` (body) |
| 5 | `/system/config` | PUT | 更新配置参数 | `data: Object` (body) |
| 6 | `/system/config/{configId}` | DELETE | 删除配置参数 | `configId: number` |
| 7 | `/system/config/export` | GET | 导出配置参数 | `query: Object` |

---

### 7. 字典类型

**文件:** `src/api/system/dict/type.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/system/dict/type/list` | GET | 查询字典类型列表 | `query: Object` |
| 2 | `/system/dict/type/{dictId}` | GET | 查询字典类型详情 | `dictId: number` |
| 3 | `/system/dict/type` | POST | 新增字典类型 | `data: Object` (body) |
| 4 | `/system/dict/type` | PUT | 更新字典类型 | `data: Object` (body) |
| 5 | `/system/dict/type/{dictId}` | DELETE | 删除字典类型 | `dictId: number` |
| 6 | `/system/dict/type/export` | GET | 导出字典类型 | `query: Object` |
| 7 | `/system/dict/type/optionselect` | GET | 获取字典类型下拉选项 | 无 |

---

### 8. 字典数据

**文件:** `src/api/system/dict/data.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/system/dict/data/list` | GET | 查询字典数据列表 | `query: Object` |
| 2 | `/system/dict/data/{dictCode}` | GET | 查询字典数据详情 | `dictCode: string` |
| 3 | `/system/dict/data/dictType/{dictType}` | GET | 按字典类型获取字典数据 | `dictType: string` |
| 4 | `/point/get8kThirdPointTypeDictData` | GET | 获取SG8000第三方测点类别字典 | 无 |
| 5 | `/system/dict/data` | POST | 新增字典数据 | `data: Object` (body) |
| 6 | `/system/dict/data` | PUT | 更新字典数据 | `data: Object` (body) |
| 7 | `/system/dict/data/{dictCode}` | DELETE | 删除字典数据 | `dictCode: number` |
| 8 | `/system/dict/data/export` | GET | 导出字典数据 | `query: Object` |

---

### 9. 同步管理

**文件:** `src/api/system/sync.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/sync/addOrUpdate` | GET | 新增/更新下级服务记录 | `query: Object` |
| 2 | `/sync/list` | GET | 查询下级服务记录列表 | `query: Object` |
| 3 | `/sync/delete` | DELETE | 删除下级服务记录 | `query: Object` |
| 4 | `/sync/updateStatus` | GET | 切换下级服务记录状态 | `data: Object` |
| 5 | `/sync/syncSettings` | POST | 配置同步设置 | `data: Object` (body) |
| 6 | `/sync/treeList` | GET | 查询已注册组织树 | `data: Object` |
| 7 | `/sync/insertNode` | POST | 拖拽节点到左侧树 | `data: Object` (body, 120s超时) |
| 8 | `/sync/updateSyncSettingsFromUp` | POST | 更新拖拽组织同步设置 | `data: Object` (body) |
| 9 | `/sync/deleteSyncOrgFromUp` | POST | 从上级删除已同步组织 | `data: Object` (body) |
| 10 | `/sync/updateUseStatusFromUp` | POST | 从上级更新同步组织状态 | `data: Object` (body) |

---

### 10. 采集器管理

**文件:** `src/api/device/device-list.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/device/list` | GET | 查询采集器列表 | `data: Object` |
| 2 | `/device/remove` | POST | 删除采集器 | `data: Object` (params) |
| 3 | `/device/sys/deviceModelList` | GET | 获取采集器型号列表 | 无 |
| 4 | `/device/config/detail` | GET | 查询采集器配置详情 | `data: Object` |
| 5 | `/device/config/configType` | GET | 获取采集器配置类型 | `data: Object` |
| 6 | `/device/config/edit` | POST | 编辑采集器配置 | `data: Object` (body) |
| 7 | `/device/config/editMult` | POST | 批量编辑采集器配置 | `data: Object` (params) |
| 8 | `/device/log/queryDeviceSysLogList` | GET | 查询采集器系统日志 | `data: Object` |
| 9 | `/device/log/queryDeviceUserLogList` | GET | 查询采集器用户日志 | `data: Object` |
| 10 | `/device/log/queryDeviceEventList` | GET | 查询采集器事件列表 | `data: Object` |
| 11 | `/gateway/getDeviceList` | GET | 从网关获取采集器列表 | `data: Object` |
| 12 | `/device/detail` | GET | 查询采集器详情 | `data: Object` |
| 13 | `/device/export` | GET | 批量导出采集器 | `data: Object` (返回blob, 60s超时) |
| 14 | `/device/add` | POST | 新增采集器 | `data: Object` (params) |
| 15 | `/device/import` | POST | 批量导入采集器 | `data: FormData` (body, 60s超时) |
| 16 | `/device/edit` | POST | 编辑采集器 | `data: Object` (params) |
| 17 | `/device/resetBattery` | POST | 复位采集器电池 | `data: Object` (params) |
| 18 | `/queryDevice` | POST | 查询采集器包列表 | 无 |
| 19 | `/device/channel/list` | GET | 查询采集器通道列表 | `data: Object` |
| 20 | `/device/channel/page` | GET | 查询通道列表(分页) | `data: Object` |
| 21 | `/device/channel/channelDataList` | GET | 查询通道数据列表 | `data: Object` |
| 22 | `/device/channel/type` | GET | 查询通道类型列表 | `data: Object` |
| 23 | `/device/channel/add` | POST | 新增通道 | `data: Object` (body) |
| 24 | `/device/channel/update` | PUT | 更新通道 | `data: Object` (body) |
| 25 | `/device/channel/delete` | DELETE | 删除通道 | `data: Object` (body) |
| 26 | `/device/sys/constant` | GET | 获取采集器常量 | 无 |
| 27 | `/device/upgrade` | POST | 批量升级采集器固件 | `data: FormData` (支持上传进度) |
| 28 | `/device/log/addDeviceEvent` | POST | 新增采集器事件 | `data: Object` (params) |
| 29 | `/device/log/editDeviceEvent` | POST | 编辑采集器事件 | `data: Object` (params) |
| 30 | `/device/log/deleteDeviceEvent` | POST | 删除采集器事件 | `data: Object` (params) |
| 31 | `/device/uploadD601Data` | GET | 下发D601数据上传指令 | `deviceId: string`, `filePath: string` |
| 32 | `/device/config/querySensorConfig` | GET | 获取D901传感器信息 | `data: Object` |
| 33 | `/device/config/saveSensorConfig` | POST | 保存D901传感器信息 | `params: Object`, `data: Object` |
| 34 | `/device/channel/modbus/export` | GET | 导出Modbus通道 | `data: Object` (返回blob) |
| 35 | `/device/channel/modbus/import` | POST | 导入Modbus通道 | `data: FormData` (multipart) |
| 36 | `/device/listByPointId` | GET | 按测点/采集器/组织获取列表 | `orgId, machineId, pointId` |

---

### 11. 设备设置（机器/组件/测点）

**文件:** `src/api/eqpt-set/index.js`（最大的API文件，涵盖机器、组件、测点、IoT、配置、图片、损伤管理）

#### 机器管理

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/machine/updateMachineBasicInfo` | POST | 更新设备基本信息 | `data: Object` (body) |
| 2 | `/machine/getMachineBasicInfo` | GET | 获取设备基本信息 | `data: Object` |
| 3 | `/machine/listMachineByOrgIdAndType` | GET | 按组织ID和类型获取设备 | `data: Object` |
| 4 | `/machine/machineList` | GET | 获取设备设置列表 | `data: Object` |
| 5 | `/machine/sort` | POST | 设备排序 | `data: Object` (params) |
| 6 | `/machine/add` | POST | 新增设备 | `data: Object` (params) |
| 7 | `/machine/edit` | POST | 编辑设备 | `data: Object` (params) |
| 8 | `/machine/remove` | POST | 删除设备 | `data: Object` (params) |
| 9 | `/machine/detail` | GET | 获取设备详情 | `data: Object` |
| 10 | `/machine/edit/param` | POST | 编辑设备参数 | `data: Object` (params) |
| 11 | `/machine/checkIfHaveAppropriateComponent` | GET | 检查是否有油浴/油雾子设备 | `machineId: string` |
| 12 | `/machine/getSg6kSubMacType` | GET | 获取SG6000设备子分类 | `data: Object` |
| 13 | `/machine/backup9KMachine` | GET | 备份SG9000机器 | `data: Object` |
| 14 | `/machine/restore9KMachine` | POST | 恢复SG9000机器 | `data: Object` (body) |
| 15 | `/machine/queryMachineListByDeviceId` | GET | 按采集器ID获取设备列表 | `deviceId: string` |

#### 组件管理

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 16 | `/component/add` | POST | 新增组件 | `data: Object` (params) |
| 17 | `/component/edit` | POST | 编辑组件 | `data: Object` (params) |
| 18 | `/component/remove` | POST | 删除组件 | `data: Object` (params) |
| 19 | `/component/listCompByMacIds` | GET | 按机器ID获取组件列表 | `data: Object` |
| 20 | `/component/getSg6kComponentSubType` | GET | 获取SG6000组件子分类 | `macSubType: number` |

#### 测点管理

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 21 | `/point/add` | POST | 新增测点 | `data: Object` (params) |
| 22 | `/point/edit` | POST | 编辑测点 | `data: Object` (params) |
| 23 | `/point/remove` | POST | 删除测点 | `data: Object` (params) |
| 24 | `/point/detail/pointIds` | GET | 查询测点详情 | `data: Object` |
| 25 | `/point/getPointInfoByName` | GET | 按名称查测点信息 | `data: Object` |
| 26 | `/point/sendProcessConfigToD901` | POST | 发送第三方工艺配置到D901 | `data: Object` (params) |
| 27 | `/point/getMoreConfigModel` | GET | 获取SG2000测点更多配置模型 | `data: Object` |
| 28 | `/point/getMoreConfig` | GET | 获取SG2000测点更多配置数据 | `data: Object` |
| 29 | `/point/updatePointConfigBatch` | POST | 批量更新测点配置 | `data: Object` (body) |
| 30 | `/point/thirdPointEdit` | POST | 保存SG8000第三方数据源配置 | `data: Object` (body) |
| 31 | `/point/thirdPoints` | GET | 查询SG8000第三方数据源配置 | `data: Object` |
| 32 | `/point/sort` | POST | 测点排序 | `data: Object` (params) |
| 33 | `/point/get` | GET | 获取测点信息 | `pointId: string` |
| 34 | `/point/getTemperaturePointUnderMachine` | GET | 获取泵下温度测点 | `machineId: string` |
| 35 | `/point/checkAmbientTemperaturePointIfValid` | GET | 验证环境温度测点有效性 | `pointIds: string` |
| 36 | `/point/editAmbientTemperatureConfig` | POST | 编辑环境温度告警配置 | 各温度阈值 (body) |
| 37 | `/point/editMultipleEigenvaluesConfig` | POST | 编辑多特征值告警配置 | 各特征值阈值 (body) |
| 38 | `/point/editUndulatingAlarmConfig` | POST | 编辑波动告警配置 | `changeRange: number` (body) |
| 39 | `/point/addPointConfig` | POST | 新增W205测点 | `data: Object` (body) |
| 40 | `/point/editPointConfig` | POST | 编辑W205测点 | `data: Object` (body) |
| 41 | `/point/editMoreConfig` | POST | 编辑W205测点更多配置 | `data: Object` (body) |
| 42 | `/point/segConfigCompute` | POST | 角域配置计算 | `params: Object`, `data: Object` (body) |
| 43 | `/point/getSegComputePointList` | GET | 获取分段计算测点列表 | `data: Object` |
| 44 | `/point/bindSampler` | POST | 绑定采集器 | `data: Object` (params) |
| 45 | `/point/unbindSampler` | POST | 解绑采集器 | `data: Object` (params) |
| 46 | `/point/changeSampler` | POST | 更换采集器 | `data: Object` (params) |

#### 参数模板

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 47 | `/paramModel/list` | GET | 查询参数表单模型 | `data: Object` |
| 48 | `/paramInfo/query` | GET | 获取设备参数信息 | `data: Object` |
| 49 | `/paramInfo/edit` | POST | 更新设备参数信息 | `data: Object` (body) |
| 50 | `/paramModel/getParamModelClassification` | GET | 获取SG6000参数模板分类 | `data: Object` |

#### 配置模型

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 51 | `/configInfo/getConfigInfoList` | GET | 获取SG6000配置列表 | `data: Object` |
| 52 | `/configModel/getConfigModel` | GET | 获取配置模型 | `data: Object` |
| 53 | `/configModel/getConfigModelList` | GET | 获取SG6000配置模型列表 | `data: Object` |
| 54 | `/configModel/getMachineType` | GET | 获取机器类型列表 | `data: Object` |
| 55 | `/configModel/getComponentType` | GET | 按机器类型获取组件类型 | `data: Object` |
| 56 | `/configModel/getPointType` | GET | 按机器类型获取测点类型 | `data: Object` |
| 57 | `/configInfo/editConfigInfo` | POST | 编辑配置 | `data: Object` (body) |
| 58 | `/configInfo/queryD901Config` | GET | 获取D901配置 | `data: Object` |
| 59 | `/configInfo/saveD901Config` | POST | 保存D901配置 | `data: Object` (body) |
| 60 | `/configInfo/queryD901Status` | GET | 查询D901状态 | `data: Object` |
| 61 | `/configInfo/uploadProductManual` | POST | 上传产品手册 | `data: FormData` (body) |

#### 8K 特有

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 62 | `/organize/getSg8kMacConfig` | GET | 获取SG8000配置 | `data: Object` |
| 63 | `/organize/editSg8kMacConfig` | POST | 保存SG8000配置 | `data: Object` (body) |
| 64 | `/organize/bindD801` | GET | 绑定D801采集器到机器 | `data: Object` |
| 65 | `/organize/unbindD801` | GET | 解绑D801采集器 | `data: Object` |
| 66 | `/organize/getSg8kPointConfigs` | GET | 获取SG8000测点告警配置 | `nodeId: string`, `nodeType: string` |
| 67 | `/organize/updateSg8kPointConfigs` | POST | 更新SG8000测点告警配置 | `data: array` (body) |
| 68 | `/organize/sg8kSelfStudy` | POST | SG8000偏差自学习 | `data: Object` (body, 支持取消) |
| 69 | `/organize/initSg8kSelfStudy` | POST | 初始化SG8000偏差自学习 | `data: Object` (body) |
| 70 | `/speedConfig/query` | GET | 获取SG8000转速配置 | `data: Object` |
| 71 | `/speedConfig/save` | POST | 保存SG8000转速配置 | `data: Object` (params) |

#### 导入导出

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 72 | `/excel/exportMachine` | GET | 批量导出设备 | `data: Object` (返回blob) |
| 73 | `/excel/exportManualInputTemplateByOrgId` | GET | 导出人工测厚模板 | `data: Object` (返回blob) |
| 74 | `/excel/importThirdPoint` | POST | 导入第三方数据源测点 | `data: FormData` (60s超时) |
| 75 | `/excel/exportThirdPoint` | GET | 导出第三方数据源测点 | `data: Object` (返回blob) |
| 76 | `/excel/importThirdDataSource` | POST | 导入第三方数据源 | `data: FormData` (60s超时) |
| 77 | `/excel/machine/import/shenghong` | POST | 导入泵检测数据 | `data: FormData` (60s超时) |
| 78 | `/excel/importSg8kPoints` | POST | 批量导入SG8000测点 | `data: Object` (body) |
| 79 | `/excel/exportSg8kPoints` | GET | 批量导出SG8000测点 | `data: Object` (返回blob) |
| 80 | `/excelNew/exportManualInputTemplateByOrgIdNew` | GET | 下载测厚数据模板 | `data: Object` (返回blob) |
| 81 | `/excel/importMachineParam` | POST | 导入机器参数 | `data: FormData` |
| 82 | `/excel/exportMachineParam` | GET | 导出机器参数 | `data: Object` (返回blob) |
| 83 | `/excel/exportMachineParamTemplate` | GET | 下载参数导入模板 | `data: Object` (返回blob) |
| 84 | `/excel/exportSensor` | GET | 导出SG9000传感器信息 | `params: Object` (返回blob) |
| 85 | `/excel/importSensor` | POST | 导入SG9000传感器信息 | `params: Object`, `data: FormData` |
| 86 | `/excel/exportModbusIn` | GET | 导出SG9000 ModbusIn | `data: Object` (返回blob) |
| 87 | `/excel/exportModbusOut` | GET | 导出ModbusOut | `data: Object` (返回blob) |
| 88 | `/excel/importModbusIn` | POST | 导入ModbusIn | `data: FormData` |

#### 损伤/图片/IoT/组织

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 89 | `/damageEntry/listByComponentId` | GET | 查询组件损伤信息 | `componentId: string` |
| 90 | `/damageEntry/add` | POST | 新增损伤记录 | `data: Object` (body, 含损伤字段) |
| 91 | `/damageEntry/edit` | POST | 编辑损伤记录 | `data: Object` (body) |
| 92 | `/damageEntry/delete` | DELETE | 删除损伤记录 | `id: string` (params) |
| 93 | `/damageEntry/getDamageCategory` | GET | 获取损伤类别 | `data: Object` |
| 94 | `/damageEntry/getDamageFactor` | GET | 获取损伤因素 | `damageCategoryCode: string` |
| 95 | `/picture/addOrEdit` | POST | 新增/编辑图片 | `data: Object` (params) |
| 96 | `/picture/remove` | POST | 删除图片 | `data: Object` (params) |
| 97 | `/picture/list` | GET | 获取设备所有图片 | `data: Object` |
| 98 | `/iot/queryDetail` | GET | 获取数采设备详情 | `data: Object` |
| 99 | `/iot/queryChannel` | GET | 获取数采通道 | `data: Object` |
| 100 | `/iot/queryType` | GET | 获取数采设备型号列表 | `data: Object` |
| 101 | `/iot/queryRelated` | GET | 获取数采设备关联信息 | `data: Object` |
| 102 | `/iot/channel/list` | GET | 获取通道信息(分页前10) | `data: Object` |
| 103 | `/iot/channel/point` | GET | 获取通道关联测点信息 | `data: Object` |
| 104 | `/organize/getOrgTreeByUserIdAndOrgId` | GET | 按用户权限获取导航树 | `data: Object` |
| 105 | `/organize/getComponentByMachineIds` | GET | 按设备ID获取组件结构 | `data: Object` |
| 106 | `/organize/getComponentPosInfo` | GET | 获取组件下测点信息 | `data: Object` |
| 107 | `/organize/getPumpOrgTreeByUser` | GET | 获取泵组织树 | `factoryId: string` |
| 108 | `/organize/getPointConfigs` | GET | 获取SG2000测点配置 | `data: Object` |
| 109 | `/organize/getOrgTreeByUser` | GET | 获取诊断用导航树 | `data: Object` |
| 110 | `/data/getUserFirstPosInfo` | POST | 获取用户默认首页测点 | `data: Object` (body) |
| 111 | `/data/getEqptParamByEqptId` | POST | 按设备ID获取设备参数 | `data: Object` (body) |

---

### 12. 8K 组织导出

**文件:** `src/api/eqpt-set/sg8kOrganize.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/organize/transfer8KMac` | GET | 迁移单台SG8000机器 | `data: Object` |
| 2 | `/organize/transferAll8KMac` | GET | 迁移全部SG8000机器 | `data: Object` |
| 3 | `/Sg8kOrganize/getCommonPath` | POST | 获取最长公共路径 | `data: Object` (body) |
| 4 | `/Sg8kOrganize/getMacPath` | POST | 获取机器完整路径 | `data: Object` (body) |

---

### 13. 文件上传

**文件:** `src/api/file/index.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/expert/file/upload` | POST | 文件上传(专家附件) | `data: FormData` (支持上传进度) |

---

### 14. 接口订阅

**文件:** `src/api/interface/index.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/interfaceSubs/list` | GET | 获取接口订阅列表 | `params: Object` |
| 2 | `/interfaceSubs/add` | POST | 新增接口订阅 | `data: Object` (body) |
| 3 | `/interfaceSubs/mqttUserList` | GET | 获取MQTT用户列表 | 无 |
| 4 | `/interfaceSubs/edit` | PUT | 编辑用户信息 | `data: Object` (body) |
| 5 | `/interfaceSubs/delete/{id}` | DELETE | 删除接口订阅 | `id: string` |
| 6 | `/interfaceSubs/addRule` | POST | 新增规则 | `data: Object` (body) |
| 7 | `/interfaceSubs/getFormatRule` | GET | 获取格式规则 | 无 |

---

### 15. 总貌图

**文件:** `src/api/map-set/index.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/overview/query` | GET | 获取总貌图标签页信息 | `data: Object` |
| 2 | `/overview/queryDetail` | GET | 获取总貌图详细配置 | `data: Object` |
| 3 | `/point/getRtData` | GET | 获取测点实时数据与详情 | `data: Object` |
| 4 | `/overview/addOrEdit` | POST | 创建/保存总貌图 | `data: Object` (body) |
| 5 | `/overview/remove` | POST | 删除总貌图 | `data: Object` (params) |
| 6 | `/overview/editOrder` | POST | 重排总貌图标签页顺序 | `data: Object` (params) |
| 7 | `/point/getMachineConf` | GET | 获取SG9000测点配置信息 | `gpids, configType` |

---

### 16. 数据字典（新版）

**文件:** `src/api/datadict/index.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/dataDict/types` | GET/DELETE/POST/PUT | 字典类型CRUD | `data: Object` |
| 2 | `/dataDict/types/datas` | GET/DELETE/POST/PUT | 字典数据CRUD | `data: Object` |
| 3 | `/dataDict/types/{dictType}/datas` | GET | 按字典类型获取字典数据 | `dictType: string` |
| 4 | `/dataDict/types/{id}/type` | GET | 按ID获取字典类型详情 | `id: string` |
| 5 | `/dataDict/types/datas?dictTypes={data}` | GET | 批量获取多类型字典数据 | `data: string`(逗号分隔) |

---

### 17. 石化通推送

**文件:** `src/api/notice/TianJinNotice.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/noticeTarget/shiHuaTong/list` | POST | 获取石化通列表 | `targetType: 50`(固定), `pageFlag: false` (body) |
| 2 | `/noticeTarget/shiHuaTong/addOrEdit` | POST | 新增/编辑石化通目标 | `orgId, targetUser, id?` (body) |
| 3 | `/noticeTarget/shiHuaTong/delete` | GET | 删除石化通目标 | `id: number` (params) |

---

### 18. 推送日志错误

**文件:** `src/api/notice/NoticeLogErrorAPI.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/noticeLogError/getList` | POST | 查询推送日志错误列表 | `query: Object` (body) |
| 2 | `/noticeLogError/modify` | POST | 修改日志状态(重发/忽略) | `data: Object` (body) |

---

### 19. 微信推送目标

**文件:** `src/api/notice/NoticeTargetAPI.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/noticeTarget/list` | POST | 获取推送目标列表(微信群) | `query: Object` (body) |
| 2 | `/noticeTarget/listChatroom` | GET | 获取所有群聊KV列表 | 无 |
| 3 | `/noticeTarget/detail` | GET | 获取推送目标详情 | `targetId, targetType` |
| 4 | `/noticeTarget/modifyDetail` | POST | 修改目标备注 | `data: Object` (body) |
| 5 | `/noticeTarget/addConfig` | POST | 添加用户到目标配置 | `data: Object` (body) |
| 6 | `/noticeTarget/modifyConfig` | POST | 修改用户到目标配置 | `data: Object` (body) |
| 7 | `/noticeTarget/removeConfig` | POST | 删除用户到目标配置 | `data: Object` (body) |
| 8 | `/noticeTarget/modifyNoticeTargetBan` | POST | 启用/禁用整体微信转发 | `data: Object` (body) |
| 9 | `/noticeTarget/modifyTargetUserConfigBan` | POST | 启用/禁用用户微信配置 | `data: Object` (body) |
| 10 | `/noticeTarget/listTargetUserConfig` | POST | 获取用户微信配置列表 | `query: Object` (body) |
| 11 | `/noticeTarget/modifyAllTargetUserConfig` | POST | 批量替换用户关联 | `query: Object` (body) |

---

### 20. 微信代理

**文件:** `src/api/notice/WechatAgentAPI.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/wechatAgent/getQR` | POST | 微信预登录(获取二维码) | `wcId?, ttuid?` (body) |
| 2 | `/wechatAgent/login` | POST | 微信登录结果轮询(等待扫码) | `verifyCode?` (body, 300s超时) |
| 3 | `/wechatAgent/logout` | POST | 微信代理登出 | `data: Object` (body, 300s超时) |
| 4 | `/wechatAgent/refreshWechatChatroom` | POST | 强制刷新微信群聊列表 | 无 (600s超时) |
| 5 | `/wechatAgent/getWechatAgentList` | GET | 获取代理机器人列表 | 无 |

---

### 21. 通用消息组

**文件:** `src/api/notice/common-group/index.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/noticeGroup/queryGroupList` | GET | 分页查询消息组 | `data: Object` |
| 2 | `/noticeGroup/addNoticeGroup` | POST | 创建消息组 | `data: Object` (body) |
| 3 | `/noticeGroup/openNoticeGroup` | POST | 开启/关闭消息组 | `data: FormData` (body) |
| 4 | `/noticeGroup/bindGroupUser` | POST | 绑定用户到消息组 | `data: FormData` (body) |
| 5 | `/noticeGroup/unbindGroupUser` | POST | 从消息组解绑用户 | `data: FormData` (body) |
| 6 | `/noticeGroup/queryGroupUserList` | GET | 分页查询组用户列表 | `data: Object` |
| 7 | `/noticeGroup/queryGroupErrlogList` | GET | 查询组错误日志列表 | `data: Object` |
| 8 | `/noticeGroup/batchDeleteGroup` | POST | 批量删除消息组 | `groupIds: string`(逗号分隔, query string) |
| 9 | `/noticeGroup/batchUpdateGroupRange` | POST | 批量更新组推送范围 | `data: FormData` (body) |
| 10 | `/noticeGroup/statusNoticeGroupUser` | POST | 切换组用户状态 | `data: FormData` (body) |
| 11 | `/noticeGroup/updateNoticeGroup` | POST | 编辑组 | `data: Object` (body) |

---

### 22. 工作流设置

**文件:** `src/api/notice/workflow-setting/index.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/flow/model/list` | GET | 获取工作流模型列表 | `data: Object` (body - GET请求带body) |
| 2 | `/flow/model/use` | GET | 启用工作流按钮 | `data: Object` (params) |
| 3 | `/flow/model/configUser` | POST | 配置一级审核人 | `data: Object` (body) |

---

### 23. 数据备份

**文件:** `src/api/backup/index.js` | **基础路径:** `/ins-os-offlinedata`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/backup/add` | POST | 创建数据备份 | `endTime: string`, `orgId: number`, `startTime: string` (body) |
| 2 | `/backup/delete` | POST | 删除数据备份 | `ids: string` (body) |
| 3 | `/backup/download/{id}` | GET | 下载备份文件 | `id: number` (返回blob) |
| 4 | `/backup/email` | POST | 邮件发送备份 | `id: number` (body) |
| 5 | `/backup/page` | GET | 分页查询备份 | `orgId, startTime, endTime, currentPage, pageSize` |

---

### 24. 数据恢复

**文件:** `src/api/restore/index.js` | **基础路径:** `/ins-os-offlinedata`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/resume/add` | POST | 创建数据恢复 | `file: file`, `orgId: number` (body) |
| 2 | `/resume/delete` | POST | 删除恢复记录 | `ids: string` (body) |
| 3 | `/resume/page` | GET | 分页查询恢复记录 | `orgId, startTime, endTime, currentPage, pageSize` |

---

### 25. 工具集（轴承库/报告/案例库等）

**文件:** `src/api/tools/index.js`

#### 轴承库

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/bearingLibrary/add` | POST | 添加轴承 | `data: Object` (body) |
| 2 | `/bearingLibrary/delete` | DELETE | 删除轴承 | `query: Object` (params) |
| 3 | `/bearingLibrary/modify` | POST | 编辑轴承信息 | `data: Object` (body) |
| 4 | `/bearingLibrary/list` | GET | 查询轴承库 | `query: Object` |
| 5 | `/bearingLibrary/validate` | GET | 验证轴承是否存在 | `query: Object` |

#### 制造商

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 6 | `/manufacturer/add` | POST | 新增制造商(未使用) | `data: Object` (body) |
| 7 | `/manufacturer/modify` | POST | 更新制造商(未使用) | `data: Object` (body) |
| 8 | `/manufacturer/delete` | DELETE | 删除制造商(未使用) | `query: Object` (params) |
| 9 | `/manufacturer/list` | GET | 查询制造商 | `query: Object` |
| 10 | `/manufacturer/checkAndAdd` | POST | 检查/添加制造商 | `data: Object` (body) |

#### 诊断事件管理

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 11 | `/diagEvent/list` | POST | 查询诊断事件列表 | `query: Object` (body) |
| 12 | `/excel/diagEventExcel/exportDataDiagEvent` | POST | 按条件导出诊断事件 | `query: Object` (body, 返回blob) |
| 13 | `/excel/diagEventExcel/exportDataDiagEventByIdList` | POST | 按ID列表导出诊断事件 | `query: Object` (body, 返回blob) |
| 14 | `/excel/diagEventExcel/getImportTemplate` | POST | 获取诊断事件导入模板 | `query: Object` (body, 返回blob) |
| 15 | `/excel/diagEventExcel/importDataDiagEvent` | POST | Excel导入诊断事件 | `query: Object` (body) |
| 16 | `/fileCommon/getImageUploadUrl` | POST | 获取OSS图片上传URL | `query: Object` (body) |
| 17 | `/diagEvent/updateClientView` | POST | 切换事件客户端可见性 | `id: string`, `clientViewState: number` (body) |
| 18 | `/diagEventLog/list` | POST | 查询诊断事件操作日志 | `query: Object` (body) |
| 19 | `/diagEventMessage/publish` | POST | 推送诊断事件到群组 | `eventId, targetIds[]` (body) |
| 20 | `/diagEventMessage/getNoticeTargetInfoByEventId` | GET | 按事件ID获取推送目标地址 | `eventId` (params) |
| 21 | `/diagEvent/detail` | POST | 获取诊断事件详情 | `id: string` (body) |
| 22 | `/diagEvent/removeList` | POST | 删除诊断事件 | `query: Object` (body) |
| 23 | `/diagEvent/updateToSystem` | POST | 分析事件转为系统事件 | `query: Object` (body) |
| 24 | `/diagEvent/updateInfo` | POST | 编辑诊断事件信息 | `query: Object` (body) |
| 25 | `/diagEventRemark/removeInfo` | POST | 删除评论 | `id: string` (body) |
| 26 | `/diagEvent/listSimple` | POST | 获取简单事件列表(关联重复事件) | `keyWord, machineId, componentId, subjectType, diagEventType, curUserId` (body) |
| 27 | `/diagEventRemark/list` | POST | 查询诊断事件评论列表 | `currentPage, pageSize, pageFlag, offset, diagEventId` (body) |

#### 报告管理

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 28 | `/report/list` | POST | 获取报告列表 | `query: Object` (body) |
| 29 | `/report/upload` | POST | 上传报告 | `query: Object` (body) |
| 30 | `/report/{reportId}` | DELETE | 删除报告/日志 | `type: string` (params) |
| 31 | `/report/log/{reportId}` | GET | 获取报告日志 | `reportId: string` |
| 32 | `/report/progress` | GET | 获取报告进度列表 | `data: Object` |
| 33 | `/report/retry/{logId}` | PUT | 重试日志 | `logId: string` |
| 34 | `/report/state/{logId}` | PUT | 修改日志状态 | `data: Object` (body) |
| 35 | `/report/generate` | POST | 上传手动生成的报告 | `query: Object` (body) |
| 36 | `/report/info/{reportId}` | PUT | 更新报告信息 | `data: Object` (body) |
| 37 | `/fileCommon/download/url/{fileId}/lastVersion` | POST | 获取最新版本文件下载URL | `fileId: string` |
| 38 | `/report/log` | POST | 记录下载操作 | `data: Object` (body) |
| 39 | `/report/templates` | GET | 获取报告模板 | `query: Object` |
| 40 | `/report/template` | POST | 新增报告模板 | `data: Object` (body) |
| 41 | `/report/template` | DELETE | 删除模板 | `ids: string[]` (params) |
| 42 | `/report/template/{id}` | PUT | 更新模板 | `data: Object` (body) |
| 43 | `/report/rules` | POST | 获取报告规则 | `query: Object` (body) |
| 44 | `/report/rule` | POST | 新增报告规则 | `query: Object` (body) |
| 45 | `/report/rule` | DELETE | 删除报告规则 | `ids: string[]` (params) |
| 46 | `/report/rule/{id}` | PUT | 更新报告规则 | `data: Object` (body) |
| 47 | `/report/rule/start/{id}` | PUT | 启动报告规则 | `id: string` |
| 48 | `/report/rule/stop/{id}` | PUT | 停止报告规则 | `id: string` |
| 49 | `/report/execRules` | POST | 执行报告规则 | `query: Object` (body) |

#### 案例库

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 50 | `/generalCaseLibrary` | GET | 查询案例库 | `query: Object` |
| 51 | `/generalCaseLibrary` | POST | 新增案例 | `data: Object` (body) |
| 52 | `/generalCaseLibrary/{reportId}` | PUT | 编辑案例 | `data: Object` (body) |
| 53 | `/generalCaseLibrary/{caseId}` | DELETE | 删除案例 | `caseId: string` |
| 54 | `/generalCaseLibrary/cases` | DELETE | 批量删除案例 | `query: Object` (params) |
| 55 | `/generalCaseLibrary/{caseId}/enable` | PUT | 启用案例 | `caseId: string` |
| 56 | `/generalCaseLibrary/{caseId}/disEnable` | PUT | 禁用案例 | `caseId: string` |

#### 视图/统计/文件

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 57 | `/setup/addUserView` | POST | 添加用户视图 | `data: Object` (body) |
| 58 | `/setup/updateUserView` | POST | 编辑用户视图 | `data: Object` (body) |
| 59 | `/setup/deleteUserView` | DELETE | 删除用户视图 | `data: Object` (params) |
| 60 | `/setup/updateUserDefaultView` | POST | 设置默认用户视图 | `data: Object` (body) |
| 61 | `/setup/getViewsByWorkSpace` | GET | 按工作空间获取视图 | `query: Object` |
| 62 | `/macEventCount/list` | GET | 获取事件统计报告 | `query: Object` |
| 63 | `/organize/getOrgTreeByUserIdAndOrgId` | GET | 获取设备树 | `query: Object` |
| 64 | `/fileCommon/upload/url` | POST | 获取文件上传URL | `query: Object` (params), `body: Object` |

---

### 26. 专家库

**文件:** `src/api/tools/expert.js`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/expert/addOrEdit` | POST | 新增/编辑专家 | `expertId?, name, serviceContent, charge, qualification, identifyAuth, attachments` (body) |
| 2 | `/expert/preview` | GET | 文件预览 | `id: string` (params, 返回arraybuffer) |
| 3 | `/expert/query` | GET | 专家分页查询 | `currentPage, pageSize, name?, serviceContent?, qualification?` |
| 4 | `/expert/deleteBatch` | POST | 批量删除专家 | `data: array` (body, IDs) |
| 5 | `/expert/editServiceContent` | POST | 批量更新服务内容 | `ids: array`, `serviceContent: string` (body) |
| 6 | `/expert/mergeFile` | POST | 合并文件分片 | `identifier: string`, `filename: string` (params) |

---

# 三、ui-ehm (设备健康管理)

## 架构概览

| 项目 | 说明 |
|------|------|
| 基础路径 | `/ins-os-view`（通过 Vite 代理到 `http://ins.shenguyun.com`） |
| HTTP 库 | Axios（单例 `PureHttp` 类封装） |
| 认证方式 | Bearer JWT Token (Cookie/localStorage获取)，自动刷新 |
| 刷新端点 | `GET /ins-os-view/refresh` → 回退 `GET /refresh` |
| 默认超时 | 40秒 |
| 参数序列化 | `qs.stringify` with `arrayFormat: "repeat"` |

---

### 1. EHM 认证与用户

**文件:** `src/api/user.ts`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 1 | `/ins-os-view/login` | POST | 加密凭证登录 | `{ loginType: "local", enCodeUser: string, enCodePassword: string, captchaPass: true }` |
| 2 | `/ins-os-view/getInfo` | GET | 获取用户信息(角色/权限/工作台配置) | 无 |
| 3 | `/ins-os-view/refresh-token` | POST | 刷新Token(手动) | `data?: object` |

#### 证据级别: 仅文档整理（EHM 认证）

- 这一组接口只负责登录态建立与刷新，和后续工作台、统计、组织树请求共用同一套鉴权上下文。
- 从路由命名看，`getInfo` 返回的不是单纯用户资料，而是工作台与权限的聚合入口。
- `refresh-token` 是前端兜底刷新入口，和自动刷新拦截器配合使用。

---

### 2. 路由配置

**文件:** `src/api/routes.ts`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 4 | `/get-async-routes` | GET | 获取异步路由配置 | 无 |

---

### 3. 工作台列表数据

**文件:** `src/api/modules/list.ts`

公共入参结构:
```typescript
interface ListRequest {
  orgIds?: string[]
  page?: number
  pageSize?: number
  deviceType?: string[]
  filter?: Record<string, any>
}
```

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 5 | `/ins-os-view/workbench/list/getEventOverview` | GET | 告警事件概览 | `ListRequest` |
| 6 | `/ins-os-view/workbench/list/getMachineRunningReport` | GET | 设备运行报告 | `ListRequest` |
| 7 | `/ins-os-view/workbench/list/getDeviceOfflineList` | GET | 设备离线列表 | `ListRequest` |
| 8 | `/ins-os-view/workbench/list/getDeviceLowBatteryList` | GET | 设备低电量列表 | `ListRequest` |
| 9 | `/ins-os-view/workbench/list/getDeviceLowRSSIList` | GET | 设备弱信号列表 | `ListRequest` |
| 10 | `/ins-os-view/workbench/list/getOverviewPicture` | GET | 机器总览图片信息 | `machineId: string, pointIds?: string, isRunningTime?: 1/0, isSpeed?: 1/0, factoryId?: string` |
| 11 | `/ins-os-view/device/listDeviceModels` | GET | 获取采集器型号列表 | `Record<string, any>` |

---

### 4. 组织结构树

**文件:** `src/api/modules/organization.ts`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 12 | `/ins-os-view/organize/getOrgTreeByUser` | GET | 获取用户组织树(含设备) | `operateType?: number/string` (0=无设备) |
| 13 | `/ins-os-view/organize/getPureOrgTreeByUser` | GET | 获取纯组织树(无设备) | `operateType?: number/string, content?: string` (支持AbortSignal) |
| 14 | `/ins-os-view/organize/getComponentByEqptIds` | GET | 按设备ID获取组件结构 | `eqptIds/equipmentIds: string, operateType?: string, factoryId?: string` |

#### 证据级别: 代码验证（EHM 组织结构树）

- `getOrgTreeByUser` 和 `getPureOrgTreeByUser` 共同构成组织树入口，前者带设备，后者去设备并支持搜索内容和 `AbortSignal`。
- `getComponentByEqptIds` 用于把设备 ID 展开成组件结构，前端通常会在工作台列表、组织树和设备详情间复用。
- 这组接口的公共特征是：都围绕组织上下文返回树/列表结构，而不是单点实体。
- 对应到当前项目后端，已确认存在统一代理入口 `GET /api/organize/tree`，其参数形状更接近 `userId/orgId/treeType/content/viewId/typeId` 这一组服务端查询参数。

---

### 5. 统计数据

**文件:** `src/api/modules/statistics.ts`

公共入参结构:
```typescript
interface StatsRequest {
  orgIds?: string[]
  deviceType?: string[]
  deviceClassification?: string[]
}
```

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 15 | `/ins-os-view/statistics/machineRunState` | GET | 设备运行状态统计 | `StatsRequest` |
| 16 | `/ins-os-view/statistics/machineHealth` | GET | 设备健康状态统计 | `StatsRequest` |
| 17 | `/ins-os-view/statistics/machineAlarmState` | GET | 设备告警状态统计 | `StatsRequest` |
| 18 | `/ins-os-view/statistics/machineType` | GET | 设备类型统计 | `StatsRequest` |
| 19 | `/ins-os-view/statistics/deviceOnline` | GET | 产品在线统计 | `StatsRequest` |
| 20 | `/ins-os-view/statistics/deviceLowBattery` | GET | 设备低电量统计 | `StatsRequest` |
| 21 | `/ins-os-view/statistics/deviceLowRSSI` | GET | 设备弱信号统计 | `StatsRequest` |
| 22 | `/ins-os-view/statistics/machineGrade` | GET | 设备等级/分类统计 | `StatsRequest` |
| 23 | `/ins-os-view/statistics/dataInput/dashboard/abnormalProcessStatus` | GET | 旋转机械异常处理状态 | `startTime: number, endTime: number, orgId: number` |
| 24 | `/ins-os-view/statistics/dataInput/dashboard/eventTrend` | GET | 旋转机械诊断事件趋势 | `startTime: number, endTime: number, orgId: number` |

#### 证据级别: 仅文档整理（EHM 统计）

- 这组接口是统计看板的聚合入口，参数大多沿用组织范围和设备分类筛选。
- `machineRunState`、`machineHealth`、`machineAlarmState` 更偏运行面板，`deviceOnline`、`deviceLowBattery`、`deviceLowRSSI` 更偏终端状态面板。
- `abnormalProcessStatus` 和 `eventTrend` 是旋转机械专题页的专项统计，不属于通用设备总览。

---

### 6. 工作台视图 CRUD

**文件:** `src/api/modules/workbench.ts`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 25 | `/ins-os-view/getInfo` | GET | 获取视图列表(从 `data.workbenches`) | 无 (缓存30s) |
| 26 | `/ins-os-view/workbench/add` | POST | 新增工作台视图 | `data: AddViewRequest` |
| 27 | `/ins-os-view/workbench/edit` | POST | 编辑工作台视图(也用于布局保存) | `data: EditViewRequest` 或 `{ id, cardList }` |
| 28 | `/ins-os-view/workbench/delete` | DELETE | 删除工作台视图 | `id: string` (params) |
| 29 | `/ins-os-view/workbench/setDefault` | POST | 设置默认视图 | `workbenchId: string/null` (params) |
| 30 | `/ins-os-view/workbench/preset/listByUserId` | GET | 获取用户预设列表 | 无 |
| 31 | `/ins-os-view/workbench/preset/add` | POST | 新增预设 | `{ title: string, config: string }` |
| 32 | `/ins-os-view/workbench/preset/update` | POST | 更新预设 | `data: unknown` |
| 33 | `/ins-os-view/workbench/preset/delete` | POST | 删除预设 | `id: string` (params) |

#### 证据级别: 代码验证（EHM 工作台视图）

- `getInfo` 提供的是工作台视图列表缓存入口，前端从中读取 `data.workbenches`。
- `add`、`edit`、`delete` 和 `setDefault` 共同完成视图 CRUD，且 `edit` 同时承担布局保存。
- `preset/*` 是工作台视图的附属能力，围绕用户保存的布局模板做增删改查。

---

### 7. EHM Demo

**文件:** `src/api/modules/ehm-demo.ts`

所有接口前缀 `/ins-os-view/ehm/demo`，可带公共参数 `factoryId?: string`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 34 | `/ins-os-view/ehm/demo/engineer/home` | GET | 工程师角色首页数据 | `factoryId?: string` |
| 35 | `/ins-os-view/ehm/demo/manager/home` | GET | 管理者角色首页数据 | `factoryId?: string` |
| 36 | `/ins-os-view/ehm/demo/events` | GET | 事件列表(按角色) | `factoryId?, role?: "engineer"/"manager"` |
| 37 | `/ins-os-view/ehm/demo/events/{eventId}` | GET | 获取单个事件详情 | `factoryId?: string` |
| 38 | `/ins-os-view/ehm/demo/events/{eventId}/generate-report` | POST | 为事件生成报告 | `factoryId?, remark?: string` |
| 39 | `/ins-os-view/ehm/demo/events/{eventId}/create-task` | POST | 为事件创建维修任务 | `factoryId?, remark?: string` |
| 40 | `/ins-os-view/ehm/demo/manager/export-briefing` | POST | 导出管理者简报 | `factoryId?, remark?: string` |

---

### 8. 案例数据库

**文件:** `src/api/modules/cases.ts`

所有接口前缀 `/ins-os-view/ehmCase/api/v1`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 41 | `/ins-os-view/ehmCase/api/v1/cases/list` | POST | 获取案例列表(分页/筛选) | `page?, page_size?, status_filter?: "DRAFT"/"PUBLISHED"/"ARCHIVED", keyword?, unit_types?: string[], equipment_types?: string[], fault_types?: string[]` |
| 42 | `/ins-os-view/ehmCase/api/v1/cases/tree` | POST | 获取案例导航树 | `status?: "DRAFT"/"PUBLISHED"/"ARCHIVED"` |
| 43 | `/ins-os-view/ehmCase/api/v1/cases/{caseId}` | GET | 获取单个案例详情 | `caseId: number/string` (路径参数) |
| 44 | `/ins-os-view/ehmCase/api/v1/search/tag` | POST | 按关键字搜索案例标签 | `keyword: string` |

---

### 9. MQTT 配置

**文件:** `src/utils/workbench/mqtt-init.ts`

| # | 接口路径 | 方法 | 功能说明 | 入参 |
|---|---------|------|---------|------|
| 45 | `/ins-os-view/getConfig` | GET | 获取MQTT代理连接配置(加密凭证) | 无 (返回mqttUsername, mqttPassword, broker/host/port/endpoint, mqttProtocol) |

---

## 附录: 统计总览

| 项目 | 接口数量(约) | API文件数 | HTTP实例数 | GET | POST | PUT | DELETE |
|------|-------------|----------|-----------|-----|------|-----|--------|
| ui-view | ~180 | 28 | 5(axon) + 1(rz.auth) | ~110 | ~55 | ~0 | ~5 |
| ui-manage | ~194 | 26 | 2(axon) | ~75 | ~95 | ~18 | ~13 |
| ui-ehm | ~45 | 9 | 1(axon) | ~30 | ~13 | ~0 | ~1 |

**公共特征:**
- 全部使用 Bearer JWT Token 认证
- Token 自动刷新端点: `/refresh` (GET)
- ui-view/ui-manage 共用 `ins-os-view` / `ins-os-manage` 后端服务
- ui-ehm 为独立的 EHM 工作台前端，重用部分 `ins-os-view` 后端接口
- 所有项目的导出接口返回 `blob` / `arraybuffer`，由前端触发浏览器下载
- ui-manage 的离线数据(备份/恢复)使用独立的 `/ins-os-offlinedata` 服务
