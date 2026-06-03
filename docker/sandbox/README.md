# Sandbox Image

沙箱容器镜像，安装 Python 依赖。代码通过挂载方式从 `skills/custom/` 加载。

## 构建

从仓库根目录执行：

```bash
docker build -f docker/sandbox/Dockerfile -t deer-flow-sandbox:latest .
```

## 文件来源

- `docker/sandbox/requirements.txt` — Python 依赖
- 代码从 `/mnt/skills/custom/` 挂载加载（沙箱启动时自动挂载）
