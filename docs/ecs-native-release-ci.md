# 可复用原生 ECS 交付流程

状态：2026-10-12，Jenkins 守卫 #3 已执行原定 5 个用例并 SUCCESS；恢复 #2 已恢复两端 NAS bind 与原 e84 容器，保持 drain。原失败记录保留。正式新镜像交付主干仍待验证。原 B/C/BC、浏览器和生命周期证据继续见 `ecs-native-shanghai-acceptance-2026-10-10.md`。

入口是 `examples/ecs-native/deploy/Jenkinsfile.native-release`，配合 `scripts/ecs_native_release.py` 与只接受可信运维输入的 `scripts/ecs_native_release_host.py`。建议新建 `deerflow-native-release` 专属任务，保留 `deerflow-shanghai-test` 的历史结果。

## 这版支持什么

同 schema 的后端 role 镜像更新：controller Gateway/MCP 和 worker resident 使用同一个新镜像，前端保持独立验收的不可变原生 UI 镜像。两库必须分别为 `0035_native_fork_compatibility` 和 `e0001_execution_ledger`。数据库迁移、首次空库初始化、前端更新、NAS 自动挂载和时间点恢复继续使用独立的人工审查流程。

构建从干净的指定 Git commit 执行 `git archive`，只构建 `backend/Dockerfile --target native-role`。release 锁记录 commit、源包 SHA、镜像 ID、镜像包 SHA/大小和两个 schema。运行日志和产物留在 Jenkins checkout 外的私有发布目录。专属 BuildKit 必须已配置最多 1 CPU / 3GiB，运行前处于 stopped 状态；作业启动它，正常退出和 SIGTERM 中断时只停止该确切容器，保留构建缓存；强制 kill、宿主机故障后仍要人工确认 builder 的状态。

## 一次性 Jenkins 准备

Jenkins 使用 Python 3.12、Git、Docker Buildx 和已有独立 builder；给 Jenkins 执行用户预建 `/data/jenkins-agent/deerflow/releases`，目录 mode0700，当前代理账户 uid999/gid987。自定义工作目录及同级 @tmp 也须提前创建为该账户所有的 mode0700，不能为此放宽公共父目录权限。不要让此任务与别的任务共享该 builder。构建需要锁文件中的依赖、基础镜像和 Chromium 下载可达；新流程的完整镜像构建尚待实际验证。

SCM 指向用户自己的 fork 或 Jenkins 本地 Git mirror，checkout 必须恰好是 `SOURCE_COMMIT`，不自动向上游仓库推送。当前远程发布暂停；通过 Git bundle 准备干净 checkout 后，设置 PREPARED_CHECKOUT=true、SOURCE_DIRECTORY=其绝对路径；完整 SOURCE_COMMIT 与干净工作树检查仍然强制执行。默认 false 保留 checkout scm。独立 guards 阶段只运行相同 5 个用例，不取部署凭据。只管理 DeerFlow 专属任务。

配置三个专属凭据：现有 SSH 凭据 `shanghai-deploy-ssh`、文件凭据 `deerflow-shanghai-known-hosts`、文件凭据 `deerflow-shanghai-release-environment`。host key 必须通过既有受信记录核验；脚本强制严格匹配。环境文件从 `release-environment.example.json` 填写并保存为 mode0600，不包含密钥或数据库 URL。

环境文件每个角色绑定私网 IP、实际 ops JSON 路径、现有 role/UI 镜像 ID、公开 Compose 文件 SHA、私有配置 fingerprint、受审查备份 generation、严格 TLS health URL 和本机 CA 路径。当前上海私有配置路径不可直接照抄示例占位路径。`config_sha256` 沿用 `ecs_executor.operations.config_fingerprint`：按固定次序拼接六个角色 JSON 和该角色 env 的文件名、NUL、原始字节、NUL。只读取私有配置计算摘要，不能输出内容。实际 ops 文件及父目录需已存在并分别为 mode0600、0700。两端另外预建 mode0700 的 `incoming_dir`；脚本不会创建 NAS 的替代本地目录。

## 守卫与四个交付阶段

同一 `RELEASE_ID` 与完整 `SOURCE_COMMIT` 贯穿四阶段，每次只执行一个阶段。发布 ID 不覆盖旧目录或旧镜像标签。

| 阶段 | 行为 | 输出 |
| --- | --- | --- |
| guards | 仅验证源码并执行 5 个无 Docker/网络的守卫用例 | Jenkins 实际日志 |
| build | 执行相同 5 个守卫用例；从指定 commit 构建后端、导出镜像 | source.tar、role-image.tar、release.json、私有 build.log |
| transfer | 核对本地包和环境 SHA，严格 SSH 传到两端，复核包、加载并验证镜像标签/ID | transfer.json |
| deploy | 两端预检；先封住 controller proxy/Gateway，再停止空闲 worker，更新 controller、重载原代理，再更新 worker | 每步 deploy-NN-role-step.json；最终 deploy.json |
| smoke | 检查两端镜像、健康、严格 TLS、worker 限额、两库版本、drain 和执行账，以及 PG/Redis/UI/proxy 容器身份 | 时间戳 smoke 回执 |

部署前必须已通过正常运维路径设置 drain，并让原生 pending/running Run、执行账未释放预约及物理 B 容器全部收尾。流程不会强制取消业务或修复执行账。fence 前后再次读取数据库，防止把不空闲的控制端当成可更新状态；只在此后停止 worker resident 及确切归属的空闲 warm AIO。数据库检查使用只读 SQL，不实例化会重新写入节点配置的 Scheduling 对象。

controller 更新只 force-recreate Gateway/MCP；PG、Redis、前端和现有代理容器保留。新应用健康后启动原代理并执行 `nginx -t`、`nginx -s reload`，严格 TLS 成功后才启动 worker。两端 ops JSON 原子更新到新镜像，并在各自私有 release 目录保留更新前副本。私有 env、六个角色定义、现有 Compose 内容和 schema 都必须匹配事先审查的摘要。

成功后仍是 **drain=true**。这里的 smoke 是交付健康检查，不是新一轮真实模型 B/C/BC 验收；没有自动 resume，也不调用模型。

## 失败与恢复

每个成功阶段立即写入独占 mode0600 回执，回执绑定 release ID、镜像包和环境 SHA。deploy 失败保留 `deploy-failure.json` 和已完成步骤，禁止同一 release 自动重放整个部署；不要删回执绕过检查。可能已封住入口、已停止 worker、或仅部分角色更新，应先读取回执并检查实际容器/ops 镜像，再按部署指南人工恢复，保持 drain。旧镜像、数据库/NAS、私有配置和失败历史都保留。

镜像传输中断保留 partial 文件；同一目标只有内容完全匹配才可复用，不自动覆盖不明内容。build 未产生 release.json 不允许进入 transfer；transfer 回执不匹配当前环境不允许 deploy。旧 release 的恢复或回滚应基于旧不可变镜像、保留的配置副本、同 schema 和明确 generation，不能倒改新的验收回执。

## 已完成的交付验证

2026-10-13 同 schema 交付主干全部通过：`deerflow-native-release` #5 build、#6 transfer、#7 deploy、#8 smoke。Release `native-20261013-5f45039e-locked`；具体源码、镜像、锁、耗时、失败历史和独立证据见 [交付验证](ecs-native-shanghai-validation-2026-10-13.md)。原五守卫通过，Chromium实际启动通过。真实DeepSeek销售工作流已在2026-10-12验证，本轮没有重跑模型。

当前两端 ops 已指向新镜像；下次恢复读取这些 ops，不能重跑固定e84恢复助手或沿用旧env中的镜像覆盖值。NAS bind仍需按部署文档恢复。再次升级时，DeerFlow环境文件凭据中的 expected_image必须重新审查并更新为届时实际安装值；本次原清单绑定e84仅用于此次升级，保留其SHA和历史回执，不篡改已有release输入。

## 受限网络的构建配置

2026-10-13 实测：宿主机 daemon 的镜像加速源不会自动传给 docker-container BuildKit。Docker Hub 直连超时，必须在 DeerFlow 专属 builder 的 buildkitd.toml 配置已有受信加速源；不要为此修改其他项目的 daemon/context。当前仅为停止中的原 builder 添加 docker.io mirror `docker.m.daocloud.io`，身份、缓存、1CPU/3GiB限额保留，配置SHA `209dc1f2a8bc843048f73f5168d1c9d5f533e6046cd96a39c5d2662cfaf9b640`。首次新建 builder 也应通过 --buildkitd-config 指向保存的配置；已有 container 的配置文件保留在 /etc/buildkit/buildkitd.toml，重建 container 时需重新准备。

Dockerfile 已有 APT_MIRROR 参数。交付入口现在接受 --apt-mirror，Jenkins 同名 APT_MIRROR 参数可填 mirrors.tuna.tsinghua.edu.cn；留空保留原默认。仅接受 DNS 主机名，不接受 URL、路径或凭据。此次同一256KiB索引样本中，Debian直连16.38秒，已用清华源1.66秒；这里只透传现有机制，不改运行时代码、依赖锁或系统发行版。其作用是已有 builder 阶段的包镜像选择，并不改变 Dockerfile 未消费该参数的步骤。

每个新 release 的 build-inputs.json 记录选定值，摘要写入镜像 org.deerflow.native.build_inputs_sha256 label 并在导出前核对，最终镜像包/ID仍由 release.json 锁定。失败和停止的目录不覆盖，重试使用新的 release ID。保持原5个守卫，只扩展输入验证断言；不增加完整矩阵或模型运行。

Jenkins 任务中断会终止整个进程组，可能在 Python finally 的 docker stop 完成前再次终止清理进程。2026-10-13 #2 ABORTED 后 builder 仍运行，已在确认任务终态与原 CID 后手工停止，缓存保留；不能把 finally/SIGTERM 支持当成 Jenkins ABORTED 必然已清理。中断后始终按回执复核并只停止原确切 builder，再开始下一次构建。


2026-10-13：release #3 的原生 Python 包直连持续慢下载；构建容器同一 Playwright wheel 样本，直连393216字节/17.65秒后超时，既有清华源2097152字节/1秒。仅正常停止本项目 #3（ABORTED）并核对确切 builder CID 后停止；缓存及失败证据保留。入口新增 `--locked-artifact-mirror` / Jenkins `LOCKED_ARTIFACT_MIRROR` 布尔开关，透传既有 Dockerfile 固定 `UV_ARTIFACT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/pypi/web`；不新增任意URL输入，不改变依赖版本、SHA、大小或锁文件恢复校验，选定布尔值写入build-inputs摘要。原5守卫内补开关断言：先RED1再GREEN5，测试仅在Jenkins代理运行；不重跑真实模型主干。该检查点之后完成上述交付。
