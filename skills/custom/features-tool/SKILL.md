---
name: features-tool
description: "InS 平台工具集 - 提供设备树分析、趋势数据获取、特征提取、诊断特征计算等基础能力。被 rotating-fault-diagnosis、pump-fault-diagnosis、reciprocating-fault-diagnosis 等专业诊断 skill 依赖。"
metadata:
  emoji: "🔧"
---

# Features Tool

InS (智能运维平台) 工具集，提供设备数据获取和特征提取的基础能力。

## 目录结构

```
features-tool/
├── ins/                    # InS API 客户端库
├── agents/                 # function_tool 装饰器
├── proto/                  # protobuf 定义
├── diagnosis/              # 诊断相关模块
├── diagnosis_rule/         # 旋转机组诊断规则
├── pump_rule/              # 机泵诊断规则
├── reciprocating_rule/     # 往复机诊断规则
├── models.py               # 模型加载
├── context_index.py        # 上下文索引
├── requirements.txt        # Python 依赖
└── tools/
    ├── diagnosis_features.py           # 诊断特征提取（Stage 2）
    ├── device_analysis_6k_tool.py      # 静设备树分析 (6K)
    ├── get_trend_data_6k_tool.py       # 静设备趋势数据 (6K)
    └── extract_trend_features_6k_tool.py # 静设备特征提取 (6K)
```

## 脚本使用

### diagnosis_features.py

诊断流水线的第二阶段，消费 `query_diagnosis.json`，生成 `diagnosis_features.json`。

```bash
python /mnt/skills/custom/features-tool/tools/diagnosis_features.py \
  --input /mnt/user-data/outputs/query_diagnosis.json \
  --focus "unbalance,misalignment" \
  --rules-skill pump-fault-diagnosis \
  --output /mnt/user-data/outputs/diagnosis_features.json
```

### 6K 系列工具（静设备/管道）

```bash
# 设备树分析
python /mnt/skills/custom/features-tool/tools/device_analysis_6k_tool.py <device_id>

# 获取趋势数据
python /mnt/skills/custom/features-tool/tools/get_trend_data_6k_tool.py <component_id> <start_time> <end_time>

# 提取趋势特征
python /mnt/skills/custom/features-tool/tools/extract_trend_features_6k_tool.py <component_id> <start_time> <end_time>
```

## 环境变量

- `INS_BASE_URL` - InS 平台地址
- `INS_ACCESS_TOKEN` - Bearer token（由 Deer Flow 运行时自动注入）
- `DIAGNOSIS_OUTPUT_DIR` - 诊断输出目录（默认 `/mnt/user-data/outputs`）
- `DIAGNOSIS_SKILLS_ROOT` - skills 根目录（默认 `/mnt/skills/custom`）

## 被依赖

- `rotating-fault-diagnosis` - 旋转机组诊断
- `pump-fault-diagnosis` - 机泵诊断
- `reciprocating-fault-diagnosis` - 往复机诊断
- `ai-report--diagnosis` - 诊断报告生成
