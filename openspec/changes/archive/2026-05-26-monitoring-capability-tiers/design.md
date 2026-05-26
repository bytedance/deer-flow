## Context

DeerFlow 监测分析当前是单层能力：所有用户获得相同的分析算法。本设计为其引入三层能力架构（Basic / Pro / Ultra），每层是系统能力的累积增强——Pro 包含 Basic 的全部能力并扩展，Ultra 包含 Pro 的全部能力并扩展。

分层不是用户可选的 `depth` 下拉参数，而是**系统级能力门控**：通过工具组 `monitoring:pro` / `monitoring:ultra` 在 Agent 配置中启用。用户在使用时感知的是"系统能做多少"，而非"我要选哪个模式"。

## Goals / Non-Goals

**Goals:**
- 定义 15 个业务功能在 Basic / Pro / Ultra 三层的具体行为差异
- 确定每层能力的算法选型、依赖项和输出格式
- 设计工具组门控机制，使 Pro/Ultra 可在租户/Agent 级别独立开关
- 保持 Basic 路径行为与当前完全一致（零回归）
- Pro/Ultra 能力在依赖缺失时优雅降级

**Non-Goals:**
- 修改 GenUI 组件库或前端代码
- 新增后端 API 路由
- 训练或微调 ML 模型（使用预训练 ONNX 模型）
- GPU 加速（CPU-only）
- 自动根据数据特征选择能力等级（用户始终通过 Agent 配置决定）

## Decisions

### D1: 工具组门控 vs 表单下拉

**选型**: 工具组门控（`monitoring:pro` / `monitoring:ultra`），不需要用户每次分析时选择。

**理由**: Pro/Ultra 是系统产品能力的体现，不是用户临时决定的分析参数。一个购买了 Pro 的租户，其监测分析 Agent 天然就运行在 Pro 能力等级上。工具组门控允许：
- 平台按租户套餐启用/禁用能力
- 租户管理员按 Agent 粒度控制（例如：日常巡检 Agent 用 Basic，故障分析 Agent 用 Pro）
- 能力等级对终端用户透明——他们只看到系统能做什么

**弃选方案**: 表单下拉 `depth: basic|pro|ultra`。让每次分析都选等级会使用户困惑（"我该选什么？"），且无法系统化地管控能力。

### D2: 包容性分层 vs 选择性分层

**选型**: 包容性分层。Pro = Basic 的全部能力 + Pro 新增能力。Ultra = Pro 的全部能力 + Ultra 新增能力。不存在"Pro 替换了 Basic 的某个算法"的情况。

**理由**: 保证了 Basic 路径的零回归。Pro 脚本在 Basic 分析基础上追加输出字段，Ultra 在 Pro 基础上再追加。报告渲染时按最高可用等级渲染。

### D3: 脚本拆分策略

**选型**: 每个能力等级的扩展逻辑写在独立脚本中。Basic 保留现有脚本不动。Pro/Ultra 新增独立脚本，接收与 Basic 相同的输入，输出 Basic 超集。

```
analysis_type = trend:
  Basic: trend_analysis.py  (现有，不改)
  Pro:   pro_trend.py       (新建，调用 trend_analysis 逻辑的超集)
  Ultra: ultra_trend.py     (新建，调用 pro_trend 逻辑的超集)
```

**理由**: 每层能力独立维护和测试。跨层共享逻辑通过导入复用（`from trend_analysis import _slope, _mean_std`），不复制粘贴。

### D4: Ultra 推理引擎

**选型**: ONNX Runtime CPU 推理，模型权重打包在 sandbox 镜像 `/opt/features-tool/models/`。

**理由**: ONNX Runtime ~30MB vs PyTorch ~800MB。推理耗时可控（单次 <5s）。模型不更新时不需 GPU。

**模型清单**:
| 模型文件 | 用途 | 输入 | 输出 |
|---------|------|------|------|
| `trend_forecaster.onnx` | 多步趋势预测 | (seq_len, n_features) | (horizon,) |
| `anomaly_autoencoder.onnx` | 异常重建误差评分 | (n_metrics,) | (n_metrics,) |
| `health_predictor.onnx` | 健康评分预测 | (n_kpis,) | (1,) |
| `spectrum_classifier.onnx` | 频谱故障分类 | (freq_bins,) | (n_classes,) |

### D5: 能力门控的执行点

工具组检查发生在 Agent SOUL.md 的 dispatch 阶段：

```
if tool_group_has("monitoring:ultra"):
    run ultra pipeline
elif tool_group_has("monitoring:pro"):
    run pro pipeline
else:
    run basic pipeline (existing)
```

Agent 启动时其 `tool_groups` 已由平台注入，SOUL.md 中的分支是静态的。

## Risks / Trade-offs

**[R] Ultra 推理耗时过长** → 单次 ONNX 推理 <5s，但 Autoencoder + LSTM + CNN 串联可能超 15s。
**M**: 脚本内部设置 120s 超时。Agent SOUL.md 中 Ultra 流水线的 `bash_timeout` 设为 180s。

**[R] ONNX 模型在 InS 实际数据上精度不足** → 预训练模型基于公开数据集，直接迁移可能效果差。
**M**: 每个 Ultra 脚本输出 `model_confidence` 字段。当 confidence < 0.6 时自动回退到 Pro 方法，并在报告中标注。后续可用 InS 实际数据微调。

**[R] 15 个功能 × 3 层 = 大量脚本和测试** → 可能超过单次交付范围。
**M**: 分阶段交付（见 Migration Plan），优先交付趋势分析和异常检测的 Pro/Ultra。

**[R] Sandbox 镜像体积膨胀** → Pro 依赖 ~80MB，Ultra 依赖 + 模型 ~120MB。
**M**: 如果成为问题，拆分为 `features-tool:pro` 和 `features-tool:ultra` 两个镜像 tag。

## Migration Plan

1. **Phase 1 — 基础设施（第 1 周）**: 新增工具组配置、sandbox 依赖安装
2. **Phase 2 — 核心分析 Pro（第 2-3 周）**: 趋势 + 异常 Pro 脚本 + Agent 分支
3. **Phase 3 — 核心分析 Ultra（第 4-5 周）**: 趋势 + 异常 Ultra 脚本 + ONNX 模型
4. **Phase 4 — 扩展能力 Pro（第 5-6 周）**: 健康 + 关联 + 图谱 Pro 脚本
5. **Phase 5 — 扩展能力 Ultra（第 7-8 周）**: 健康 + 关联 + 图谱 Ultra 脚本
6. **Phase 6 — 运行与交互（第 8-10 周）**: 调度、呈现、报告、闭环、交互、对比、建议

每阶段独立可交付，不阻塞后续阶段。

## Open Questions

1. ONNX 模型来源：自训练还是使用公开预训练模型？如果自训练，训练数据和流水线由谁负责？
2. Ultra 的 NL 交互能力是否依赖 LLM 推理？如果是，是否需要独立的 agent 实例？
3. 事件驱动的分析调度（Ultra 调度）如何接收触发事件？是否需要接入 InS 告警流？
