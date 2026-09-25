# 🚀 DeerFlow Google Drive 集成技能 - 最终版本

## 📋 版本信息

- **版本**: 1.0.0
- **发布日期**: 2026-03-31
- **兼容性**: DeerFlow 2.x + Python 3.8+

---

## 📦 完整目录结构

```
google-drive-final/
├── FINAL_VERSION.md           # 本文档
├── install.sh                 # 一键安装脚本
├── SKILL.md                   # 技能定义
├── README.md                  # 完整使用文档
├── QUICKSTART.md              # 5分钟快速开始
├── requirements.txt           # Python 依赖
├── test_document.txt          # 测试文件
│
├── scripts/                   # 核心脚本
│   ├── utils.py              # 通用工具函数
│   ├── auth_setup.py         # OAuth 认证设置
│   ├── list_files.py         # 列出文件
│   ├── read_file.py          # 读取文件
│   ├── create_file.py        # 创建/上传文件
│   ├── update_file.py        # 更新文件
│   └── search_files.py       # 搜索文件
│
├── assets/                    # 附加资源
│   └── langgraph_integration_example.py
│
├── references/                # 参考文档
│   └── google-drive-api.md
│
└── evals/                     # 评估测试
    └── test_drive_basic.py
```

---

## 🚀 快速开始（3步）

### 1️⃣ 安装技能

```bash
# 解压后运行安装脚本
cd google-drive-final
./install.sh
```

### 2️⃣ 配置认证

```bash
# 进入技能目录
cd ~/deer-flow/skills/custom/google-drive

# 安装依赖
pip install -r requirements.txt

# 获取 credentials.json 并放在当前目录，然后运行：
python scripts/auth_setup.py
```

### 3️⃣ 测试上传

```bash
# 上传测试文件
python scripts/create_file.py upload test_document.txt --name "DeerFlow_Test.txt"
```

---

## 📝 核心功能说明

### 📂 文件操作

| 功能 | 命令 |
|------|------|
| **列出文件** | `python scripts/list_files.py` |
| **读取文件** | `python scripts/read_file.py <file-id>` |
| **上传文件** | `python scripts/create_file.py upload <local-file>` |
| **创建文件夹** | `python scripts/create_file.py folder <name>` |
| **搜索文件** | `python scripts/search_files.py <query>` |

### 🔐 认证流程

1. 访问 [Google Cloud Console](https://console.cloud.google.com/)
2. 创建项目 → 启用 Drive API → 创建 OAuth 凭证（桌面应用）
3. 下载 `credentials.json` → 运行 `auth_setup.py` → 完成浏览器授权

---

## 🐳 Docker 集成

### 确认卷挂载

检查 `docker-compose.yml`：

```yaml
services:
  backend:
    volumes:
      - ./skills:/app/backend/skills  # ✅ 需要这行
```

### 重启 DeerFlow

```bash
cd ~/deer-flow
make down && make up
```

---

## 📚 更多文档

- `README.md` - 完整的使用文档
- `QUICKSTART.md` - 5分钟快速上手指南
- `references/google-drive-api.md` - Google Drive API 参考

---

## 🔧 故障排除

### 常见问题

**Q: 认证失败？**
- 检查 `credentials.json` 是否正确
- 确认 API 是否已启用
- 尝试删除 `token.json` 重新认证

**Q: Docker 看不到技能？**
- 确认 `docker-compose.yml` 有正确的 volume 挂载
- 文件权限问题：`chmod -R 755 ~/deer-flow/skills`
- 重启 Docker 服务

**Q: 依赖安装失败？**
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 📄 许可证

MIT License - 可自由使用、修改和分发

---

## 🆘 获取帮助

如有问题，请检查：
1. DeerFlow 日志
2. Google Cloud Console API 状态
3. 网络连接

---

**🎉 祝您使用愉快！**
