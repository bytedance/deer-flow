# 安装指南

DeerFlow 的快速安装说明。

## 配置初始化

DeerFlow 使用 YAML 配置文件，且该文件应放在**项目根目录**。

### 步骤

1. **进入项目根目录**：
   ```bash
   cd /path/to/deer-flow
   ```

2. **复制示例配置**：
   ```bash
   cp config.example.yaml config.yaml
   ```

3. **编辑配置**：
   ```bash
   # 方案 A：设置环境变量（推荐）
   export OPENAI_API_KEY="your-key-here"

   # 可选：当你从其他目录运行时，固定项目根目录
   export DEER_FLOW_PROJECT_ROOT="/path/to/deer-flow"

   # 方案 B：直接编辑 config.yaml
   vim config.yaml  # 或你偏好的编辑器
   ```

4. **验证配置**：
   ```bash
   cd backend
   python -c "from deerflow.config import get_app_config; print('✓ Config loaded:', get_app_config().models[0].name)"
   ```

## 重要说明

- **位置**：`config.yaml` 应位于 `deer-flow/`（项目根目录）
- **Git**：`config.yaml` 会被 git 自动忽略（包含敏感信息）
- **运行时根目录**：若 DeerFlow 可能从项目根目录之外启动，请设置 `DEER_FLOW_PROJECT_ROOT`
- **运行时数据**：状态默认存储在项目根目录下的 `.deer-flow`；可通过 `DEER_FLOW_HOME` 修改
- **技能目录**：默认使用项目根目录下的 `skills/`；可通过 `DEER_FLOW_SKILLS_PATH` 或 `skills.path` 修改

## 配置文件查找位置

后端会按以下顺序查找 `config.yaml`：

1. 代码中显式传入的 `config_path` 参数
2. 环境变量 `DEER_FLOW_CONFIG_PATH`（若已设置）
3. `DEER_FLOW_PROJECT_ROOT` 下的 `config.yaml`；若未设置 `DEER_FLOW_PROJECT_ROOT`，则查找当前工作目录下的 `config.yaml`
4. 为兼容单仓库结构保留的 legacy backend/repository-root 位置

**推荐**：将 `config.yaml` 放在项目根目录（`deer-flow/config.yaml`）。

## 沙箱初始化（可选但推荐）

如果你计划使用基于 Docker/容器的沙箱（在 `config.yaml` 中配置 `sandbox.use: deerflow.community.aio_sandbox:AioSandboxProvider`），强烈建议预先拉取容器镜像：

```bash
# 在项目根目录执行
make setup-sandbox
```

**为什么要预拉取？**
- 沙箱镜像（约 500MB+）首次使用时才拉取，会导致较长等待
- 预拉取可以提供清晰的进度反馈
- 避免首次使用 agent 时产生困惑

如果你跳过该步骤，镜像会在首次执行 agent 时自动拉取，具体耗时取决于你的网络速度，可能需要数分钟。

## 故障排查

### 找不到配置文件

```bash
# 检查后端正在从哪里查找配置
cd deer-flow/backend
python -c "from deerflow.config.app_config import AppConfig; print(AppConfig.resolve_config_path())"
```

如果仍找不到配置：
1. 确保你已将 `config.example.yaml` 复制为 `config.yaml`
2. 确认当前位于项目根目录，或已设置 `DEER_FLOW_PROJECT_ROOT`
3. 检查文件是否存在：`ls -la config.yaml`

### 权限不足（Permission denied）

```bash
chmod 600 ../config.yaml  # 保护敏感配置
```

## 另请参阅

- [配置指南](CONFIGURATION.md) - 详细配置选项
- [架构总览](../CLAUDE.md) - 系统架构
