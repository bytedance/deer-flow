# 用户隔离验证指南

## 快速验证步骤

### 1. 清理测试数据

```bash
# 删除用户数据文件
rm -f backend/.deer-flow/users/users.json
```

### 2. 启动应用

```bash
# 启动所有服务
make dev
```

或者只启动 Gateway：

```bash
# 设置JWT密钥
export DEER_FLOW_JWT_SECRET="test-secret"

# 启动 Gateway
cd backend
uv run uvicorn src.gateway.app:app --host 0.0.0.0 --port 8001
```

### 3. 注册两个测试用户

**用户1:**
```bash
curl -X POST http://localhost:8001/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user1@test.com", "password": "password123"}'
```

**响应示例:**
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user_id": "abc123...",
  "email": "user1@test.com",
  "role": "user"
}
```

**用户2:**
```bash
curl -X POST http://localhost:8001/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user2@test.com", "password": "password123"}'
```

**验证:** 两个 `user_id` 应该不同！

### 4. 验证用户信息隔离

**获取用户1信息:**
```bash
TOKEN1="<user1的token>"
curl -X GET http://localhost:8001/api/auth/me \
  -H "Authorization: Bearer $TOKEN1"
```

应该看到:
```json
{
  "user_id": "用户1的ID",
  "email": "user1@test.com",
  "role": "user"
}
```

**获取用户2信息:**
```bash
TOKEN2="<user2的token>"
curl -X GET http://localhost:8001/api/auth/me \
  -H "Authorization: Bearer $TOKEN2"
```

应该看到:
```json
{
  "user_id": "用户2的ID",
  "email": "user2@test.com",
  "role": "user"
}
```

**验证:** 每个用户只能看到自己的信息！

### 5. 验证内存数据隔离

**保存不同的内存数据:**

```python
# 在Python中执行
import sys
sys.path.insert(0, 'backend/src')

from src.agents.memory.updater import _save_memory_to_file, _create_empty_memory
from src.gateway.middleware.auth import decode_access_token

token1 = "<user1的token>"
user1_id = decode_access_token(token1).user_id

# 保存用户1的memory
mem1 = _create_empty_memory()
mem1['user']['workContext']['summary'] = '用户1的独占数据'
_save_memory_to_file(mem1, user_id=user1_id)

token2 = "<user2的token>"
user2_id = decode_access_token(token2).user_id

# 保存用户2的memory
mem2 = _create_empty_memory()
mem2['user']['workContext']['summary'] = '用户2的不同数据'
_save_memory_to_file(mem2, user_id=user2_id)
```

**通过API读取memory:**

```bash
# 读取用户1的memory
curl -X GET http://localhost:8001/api/memory \
  -H "Authorization: Bearer $TOKEN1"
```

应该看到 `"summary": "用户1的独占数据"`

```bash
# 读取用户2的memory
curl -X GET http://localhost:8001/api/memory \
  -H "Authorization: Bearer $TOKEN2"
```

应该看到 `"summary": "用户2的不同数据"`

**验证:** 用户1和用户2看到的是不同的memory数据！

### 6. 验证文件系统隔离

```bash
# 查看用户目录
ls -la backend/.deer-flow/users/
```

应该看到:
```
backend/.deer-flow/users/
├── users.json
├── 用户1的ID/
│   └── memory.json
└── 用户2的ID/
    └── memory.json
```

**验证:** 每个用户有独立的目录！

### 7. 验证向后兼容性

```bash
# 不带token的请求
curl -X GET http://localhost:8001/api/auth/me
```

应该看到:
```json
{
  "user_id": "default",
  "email": "default@example.com",
  "role": "user"
}
```

**验证:** 未认证请求使用默认用户！

## 验证清单

- [ ] 两个用户有不同的 `user_id`
- [ ] `/api/auth/me` 返回各自用户的信息
- [ ] `/api/memory` 返回各自用户的内存数据
- [ ] 文件系统中每个用户有独立目录
- [ ] 无token请求使用默认用户

## 如果验证失败

**问题1: 端口已被占用**
```bash
# 停止现有Gateway
pkill -f "uvicorn src.gateway.app:app"
```

**问题2: 用户已存在**
```bash
# 删除用户数据重新开始
rm -f backend/.deer-flow/users/users.json
```

**问题3: JWT secret未设置**
```bash
# 设置JWT密钥
export DEER_FLOW_JWT_SECRET="$(openssl rand -base64 32)"
```

## 成功标志

如果所有验证都通过，说明多租户用户隔离功能正常工作：
- ✅ 用户认证系统正常
- ✅ 数据隔离正常
- ✅ 向后兼容性保持
