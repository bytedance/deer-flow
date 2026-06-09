# 故障码表 — 旋转机组异常研判

来源：`vibration-fault-diagnosis` skill 精简版。

## 故障码表（12个）

| code | 中文名 | 关键特征 |
|------|--------|---------|
| `unbalance_1x` | 不平衡 | 1X 主导 + 长期稳定高位 |
| `misalignment` | 不对中 | 联端突出 + 1X 主导 |
| `critical_response` | 临界响应大 | 启停过临界转速带响应剧增 |
| `thermal_bend` | 转子热弯曲 | 稳速/升速段四通道同升 |
| `permanent_bend` | 转子永久性弯曲 | 低速段已偏高 + 椭圆轨迹 |
| `rub_seal` | 动静摩擦/密封摩擦 | 削顶/毛刺/分数次谐波 |
| `support_bearing` | 支撑轴承装配/软脚/刚度差异 | XY 差异/刚度方向性 |
| `rotating_stall_surge` | 旋转失速/喘振 | 低频不稳定/工艺联动 |
| `runout` | 晃度（测量效应） | 低速、每周期跳变且 XY 相差约90° |
| `axial_offset_calibration` | 轴位移零点调校异常 | 检修后轴位移突高但温度正常 |
| `bearing_temperature_high` | 支撑轴承温度异常 | 启动即高且平 |
| `thrust_bearing_temperature_high` | 推力轴承温度异常 | 双通道高且平 |

---

## 快速特征映射

| 观测特征 | 疑似故障 |
|---------|---------|
| 1X 主导 + 正弦 + 长期稳定 | `unbalance_1x` |
| 联端突出 + 1X 主导 | `misalignment` |
| 启停过临界转速带剧增 | `critical_response` |
| 四通道同升 + 稳速段 | `thermal_bend` |
| 低速已高 + 椭圆轨迹 | `permanent_bend` |
| 削顶/毛刺 + 分数次谐波 | `rub_seal` |
| 同一轴承 XY 差异大 | `support_bearing` |
| 低频不稳定 + 工艺联动 | `rotating_stall_surge` |
| 低速每周期跳变 + XY 差90° | `runout` |
| 检修后轴位移高 + 温度正常 | `axial_offset_calibration` |
| 启动即高且平（单通道） | `bearing_temperature_high` |
| 双通道温度高且平 | `thrust_bearing_temperature_high` |

---

## 事件类型 → 研判要点

### `sensor` — 传感器异常
- 同位置多测点互校：X/Y同时跳变 → 真实物理变化；仅单点 → 传感器故障
- 跳变形态：瞬时阶跃→接触不良；冻结→死机；归零→断线/短路
- 与 runStatus 关联：无变化→传感器故障

### `t` — 阈值超限
- 超限幅度×持续时间：轻微短时→工况波动；大幅持续→真实劣化
- 多点一致性：联端X/Y+非联端同步→转子问题；仅联端→对中
- 频谱特征：1X→不平衡；2X→不对中；0.3-0.8X→油膜涡动；高频→轴承/齿轮
- 趋势走向：恢复→工况波动；持续高位→真实劣化

### `w` — 波动异常
- 频率：1X→不平衡波动；0.3-0.8X→油膜涡动；<0.3X→喘振
- 幅度：<20%→正常；>50%→异常
- 工艺关联：同步→工艺扰动；仅振动→机械问题

### `k` — 趋势异常
- 30天趋势斜率 + 剩余时间外推 + 同类设备对比

### `d` — 升速曲线偏差
- 偏差模式 + 历史对比
