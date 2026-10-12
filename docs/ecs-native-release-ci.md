# 可复用原生 ECS 交付流程

状态：2026-10-12，代码已准备；新 Jenkins 流水线尚未在上海执行。两台 ECS 由用户停机，本文不把静态检查称为云端部署验收。原 B/C/BC、浏览器和生命周期证据继续见 `ecs-native-shanghai-acceptance-2026-10-10.md`。

入口是 `examples/ecs-native/deploy/Jenkinsfile.native-release`，配合 `scripts/ecs_native_release.py` 与只接受可信运维输入的 `scripts/ecs_native_release_host.py`。建议新建 `deerflow-native-release` 专属任务，保留 `deerflow-shanghai-test` 的历史结果。

## 这版支持什么

同 schema 的后端 role 镜像更新：controller Gateway/MCP 和 worker resident 使用同一个新镜像，前端保持独立验收的不可变原生 UI 镜像。两库必须分别为 `0035_native_fork_compatibility` 和 `e0001_execution_ledger`。数据库迁移、首次空库初始化、前端更新、NAS 自动挂载和时间点恢复继续使用独立的人工审查流程。

构建从干净的指定 Git commit 执行 `git archive`，只构建 `backend/Dockerfile --target native-role`。release 锁记录 commit、源包 SHA、镜像 ID、镜像包 SHA/大小和两个 schema。运行日志和产物留在 Jenkins checkout 外的私有发布目录。专属 BuildKit 必须已配置最多 1 CPU / 3GiB，运行前处于 stopped 状态；作业启动它，正常退出和 SIGTERM 中断时只停止该确切容器，保留构建缓存；强制 kill、宿主机故障后仍要人工确认 builder 的状态。

## 一次性 Jenkins 准备

Jenkins 使用 Python 3.12、Git、Docker Buildx 和已有独立 builder；给 Jenkins 执行用户预建 `/data/jenkins-agent/deerflow/releases`，目录 mode0700。不要让此任务与别的任务共享该 builder。构建需要锁文件中的依赖、基础镜像和 Chromium 下载可达；新流程的完整镜像构建尚待实际验证。

SCM 指向用户自己的 fork 或 Jenkins 本地 Git mirror，checkout 必须恰好是 `SOURCE_COMMIT`，不自动向上游仓库推送。当前远程发布暂停；必要时可在恢复测试时通过 Git bundle 提供本地 mirror，再单独核对 commit。仅作业创建和执行阶段需要 Jenkins 变更，本次没有修改线上 Jenkins 任务。

配置三个专属凭据：现有 SSH 凭据 `shanghai-deploy-ssh`、文件凭据 `deerflow-shanghai-known-hosts`、文件凭据 `deerflow-shanghai-release-environment`。host key 必须通过既有受信记录核验；脚本强制严格匹配。环境文件从 `release-environment.example.json` 填写并保存为 mode0600，不包含密钥或数据库 URL。

环境文件每个角色绑定私网 IP、实际 ops JSON 路径、现有 role/UI 镜像 ID、公开 Compose 文件 SHA、私有配置 fingerprint、受审查备份 generation、严格 TLS health URL 和本机 CA 路径。当前上海私有配置路径不可直接照抄示例占位路径。`config_sha256` 沿用 `ecs_executor.operations.config_fingerprint`：按固定次序拼接六个角色 JSON 和该角色 env 的文件名、NUL、原始字节、NUL。只读取私有配置计算摘要，不能输出内容。实际 ops 文件及父目录需已存在并分别为 mode0600、0700。两端另外预建 mode0700 的 `incoming_dir`；脚本不会创建 NAS 的替代本地目录。

## 四个显式阶段

同一 `RELEASE_ID` 与完整 `SOURCE_COMMIT` 贯穿四阶段，每次只执行一个阶段。发布 ID 不覆盖旧目录或旧镜像标签。

| 阶段 | 行为 | 输出 |
| --- | --- | --- |
| build | 执行 5 个无 Docker/网络的交付守卫单测；从指定 commit 构建后端、导出镜像 | source.tar、role-image.tar、release.json、私有 build.log |
| transfer | 核对本地包和环境 SHA，严格 SSH 传到两端，复核包、加载并验证镜像标签/ID | transfer.json |
| deploy | 两端预检；先封住 controller proxy/Gateway，再停止空闲 worker，更新 controller、重载原代理，再更新 worker | 每步 deploy-NN-role-step.json；最终 deploy.json |
| smoke | 检查两端镜像、健康、严格 TLS、worker 限额、两库版本、drain 和执行账，以及 PG/Redis/UI/proxy 容器身份 | 时间戳 smoke 回执 |

部署前必须已通过正常运维路径设置 drain，并让原生 pending/running Run、执行账未释放预约及物理 B 容器全部收尾。流程不会强制取消业务或修复执行账。fence 前后再次读取数据库，防止把不空闲的控制端当成可更新状态；只在此后停止 worker resident 及确切归属的空闲 warm AIO。数据库检查使用只读 SQL，不实例化会重新写入节点配置的 Scheduling 对象。

controller 更新只 force-recreate Gateway/MCP；PG、Redis、前端和现有代理容器保留。新应用健康后启动原代理并执行 `nginx -t`、`nginx -s reload`，严格 TLS 成功后才启动 worker。两端 ops JSON 原子更新到新镜像，并在各自私有 release 目录保留更新前副本。私有 env、六个角色定义、现有 Compose 内容和 schema 都必须匹配事先审查的摘要。

成功后仍是 **drain=true**。这里的 smoke 是交付健康检查，不是新一轮真实模型 B/C/BC 验收；没有自动 resume，也不调用模型。

## 失败与恢复

每个成功阶段立即写入独占 mode0600 回执，回执绑定 release ID、镜像包和环境 SHA。deploy 失败保留 `deploy-failure.json` 和已完成步骤，禁止同一 release 自动重放整个部署；不要删回执绕过检查。可能已封住入口、已停止 worker、或仅部分角色更新，应先读取回执并检查实际容器/ops 镜像，再按部署指南人工恢复，保持 drain。旧镜像、数据库/NAS、私有配置和失败历史都保留。

镜像传输中断保留 partial 文件；同一目标只有内容完全匹配才可复用，不自动覆盖不明内容。build 未产生 release.json 不允许进入 transfer；transfer 回执不匹配当前环境不允许 deploy。旧 release 的恢复或回滚应基于旧不可变镜像、保留的配置副本、同 schema 和明确 generation，不能倒改新的验收回执。

## 待开机后一次验证

先确认两台机器的新公网 IP 和既有私网身份，恢复 NAS/bind/marker，使用既有 e84 镜像按当前部署指南恢复，保持 drain。然后检查新的 Jenkins 源码输入、builder 和私有环境清单，依次验证新流水线四阶段。先跑交付主干，成功后只选一个真实业务工作流冒烟；不用重跑已经通过的全部测试矩阵。当前新流程的 5 个守卫单测及实际构建/传输/部署均列为待 Jenkins 执行。

本次静态证据：Ruff check/format、三个 Python 文件语法编译、示例 JSON、三个 Jenkins shell 段的 sh -n、OpenSpec 严格校验及 67 个历史输入 SHA 一致性均通过。没有执行新守卫单测、Groovy/Jenkins 解析、Docker 构建或云端交付；这些待开机后在 Jenkins 验证。
