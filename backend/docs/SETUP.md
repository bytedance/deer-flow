# DeerFlow 设置指南

===================
设计思路说明
===================

**为什么需要设置指南**：
1. **降低入门门槛**：为新用户提供清晰的配置步骤
2. **避免常见错误**：提前说明配置位置和优先级
3. **安全最佳实践**：指导用户正确处理敏感信息
4. **故障排查**：提供常见问题的解决方案

**配置设计原则**：
- **约定优于配置**：提供合理的默认值
- **环境变量优先**：支持通过环境变量覆盖配置
- **多位置搜索**：灵活的配置文件搜索策略
- **安全第一**：自动忽略包含密钥的配置文件

## 配置文件设置

DeerFlow使用YAML配置文件，该文件应该放置在**项目根目录**中。

**为什么使用YAML配置**：
- **可读性**：YAML格式易于人类阅读和编辑
- **层次结构**：支持嵌套配置，适合复杂配置
- **注释支持**：允许在配置文件中添加说明
- **广泛支持**：YAML是配置文件的标准格式

### 设置步骤

1. **Navigate to project root**:
   ```bash
   cd /path/to/deer-flow
   ```

2. **Copy example configuration**:
   ```bash
   cp config.example.yaml config.yaml
   ```

3. **Edit configuration**:
   ```bash
   # Option A: Set environment variables (recommended)
   export OPENAI_API_KEY="your-key-here"

   # Option B: Edit config.yaml directly
   vim config.yaml  # or your preferred editor
   ```

4. **Verify configuration**:
   ```bash
   cd backend
   python -c "from deerflow.config import get_app_config; print('✓ Config loaded:', get_app_config().models[0].name)"
   ```

## 重要注意事项

**为什么需要注意这些配置细节**：

- **位置要求**：`config.yaml`应该放在`deer-flow/`（项目根目录），而不是`deer-flow/backend/`
  - **原因**：配置文件是项目级别的，不特定于backend目录

- **Git自动忽略**：`config.yaml`被git自动忽略（包含密钥）
  - **安全考虑**：防止敏感信息（API密钥）被提交到版本控制

- **优先级规则**：如果`backend/config.yaml`和`../config.yaml`都存在，backend版本优先
  - **灵活性**：允许特定环境的本地覆盖

## 配置文件搜索位置

- **Location**: `config.yaml` should be in `deer-flow/` (project root), not `deer-flow/backend/`
- **Git**: `config.yaml` is automatically ignored by git (contains secrets)
- **Priority**: If both `backend/config.yaml` and `../config.yaml` exist, backend version takes precedence

## Configuration File Locations

The backend searches for `config.yaml` in this order:

1. `DEER_FLOW_CONFIG_PATH` environment variable (if set)
2. `backend/config.yaml` (current directory when running from backend/)
3. `deer-flow/config.yaml` (parent directory - **recommended location**)

**Recommended**: Place `config.yaml` in project root (`deer-flow/config.yaml`).

## 沙箱设置（可选但推荐）

**为什么需要沙箱**：
- **代码隔离**：在隔离环境中执行不可信代码
- **安全防护**：防止恶意代码破坏宿主系统
- **资源控制**：限制CPU、内存和磁盘使用
- **可移植性**：确保执行环境的一致性

**为什么推荐预拉取镜像**：

If you plan to use Docker/Container-based sandbox (configured in `config.yaml` under `sandbox.use: deerflow.community.aio_sandbox:AioSandboxProvider`), it's highly recommended to pre-pull the container image:

```bash
# From project root
make setup-sandbox
```

**Why pre-pull?**
- The sandbox image (~500MB+) is pulled on first use, causing a long wait
- Pre-pulling provides clear progress indication
- Avoids confusion when first using the agent

If you skip this step, the image will be automatically pulled on first agent execution, which may take several minutes depending on your network speed.

## 故障排查

### 配置文件未找到

**为什么会出现这个问题**：
- 配置文件位置不正确
- 从错误的目录启动应用
- 环境变量设置错误

```bash
# Check where the backend is looking
cd deer-flow/backend
python -c "from deerflow.config.app_config import AppConfig; print(AppConfig.resolve_config_path())"
```

If it can't find the config:
1. Ensure you've copied `config.example.yaml` to `config.yaml`
2. Verify you're in the correct directory
3. Check the file exists: `ls -la ../config.yaml`

### 权限被拒绝

**为什么需要设置正确的文件权限**：
- **保护敏感信息**：配置文件包含API密钥等敏感信息
- **最小权限原则**：只有所有者需要读写权限
- **安全最佳实践**：防止其他用户读取密钥

```bash
chmod 600 ../config.yaml  # 保护敏感配置，只有所有者可读写
```

**为什么使用600权限**：
- `6` (所有者): 读+写权限
- `0` (组): 无权限
- `0` (其他): 无权限

## 参考文档

- [配置指南](CONFIGURATION.md) - 详细的配置选项说明
- [架构概述](../CLAUDE.md) - 系统架构设计