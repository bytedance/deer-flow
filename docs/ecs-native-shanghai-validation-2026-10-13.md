# 上海恢复与交付验证（2026-10-13）

Controller101.132.36.217 / 私网192.168.0.190；Worker139.196.37.75 / 私网192.168.0.189。原 host key、实例身份、NAS 和 e84 镜像保留。

- 独立 deerflow-native-recovery-20261013 #1 SUCCESS，127.360秒。两端原 NFS 已挂载、namespace bind缺失；恢复原 bind和容器，严格 TLS、配置 fingerprint、三表历史摘要保留；drain=true/unreleased=0，无模型调用。回执SHA ae1b2c14dd603b31b97957fc8833d2028c7d5c491f2103c5595cb565209f6445；consoleSHA fb5c99e1db644d014da9427e5981c159e6e5a019de4d5bd1536b0a547a617ce6。
- 新任务 deerflow-native-release #1 FAILURE，源码6131c0f2，原5守卫通过0.028秒；隔离 BuildKit 未继承daemon镜像源，Docker Hub metadata直连超时。consoleSHA671ae7e2c3d2277a69b66f66b01da1243bb7ff28419ac4418da79ae5e1f2855a。保留 native-20261013-6131c0f2 目录。
- 验证既有镜像源实际manifest后，只在原专属停止中的 builder 添加 docker.io mirror=docker.m.daocloud.io。原CID与1CPU/3GiB/零swap预算不变，配置SHA209dc1f2a8bc843048f73f5168d1c9d5f533e6046cd96a39c5d2662cfaf9b640。
- #2 使用新目录 native-20261013-6131c0f2-mirror，基础镜像加载成功并进入APT安装。256KiB实际索引样本：Debian16.38秒，既有清华源1.66秒。因新CLI遗漏已有APT_MIRROR透传，正常停止该构建并保留cache/log。终态ABORTED；Jenkins进程组终止使finally未完成，核对原CID后手工停止builder，没有停止其他容器。
- 修复仅透传Dockerfile已有APT_MIRROR；验证DNS主机名输入并保存build-inputs摘要到镜像标签。现有5守卫内补断言，不增加用例数量：Jenkins代理账户 RED1（SHA49595c710733f85c1486797fdb65015b8fe47a0e86db9a1e436264e48b76528a），随后 GREEN5（0.025秒）；Ruff检查及格式通过。
- 已准备两个DeerFlow文件凭据，分别存放非秘密环境清单与受信known_hosts；原SSH凭据保持不变。清单SHA17392c5a173c6c6b99ffeae03d4568a42b7028d1e7b13ebf47481a0eae60f937，绑定实际两端路径、私有配置/Compose摘要、原e84和独立UI镜像。generation沿用已验收兼容类；不声称新增数据库备份或PITR。

证据留在 Jenkins /data/jenkins-agent/deerflow/native-release-recovery-20261013，既有昨日业务证明/文件和失败历史未覆盖。昨天真实销售C→B→C已通过，本轮不重跑模型矩阵。此前阶段角色仍为原e84；以下记录最终新镜像交付。远程Git发布保持暂停。


2026-10-13：release #3 的原生 Python 包直连持续慢下载；构建容器同一 Playwright wheel 样本，直连393216字节/17.65秒后超时，既有清华源2097152字节/1秒。仅正常停止本项目 #3（ABORTED）并核对确切 builder CID 后停止；缓存及失败证据保留。入口新增 `--locked-artifact-mirror` / Jenkins `LOCKED_ARTIFACT_MIRROR` 布尔开关，透传既有 Dockerfile 固定 `UV_ARTIFACT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/pypi/web`；不新增任意URL输入，不改变依赖版本、SHA、大小或锁文件恢复校验，选定布尔值写入build-inputs摘要。原5守卫内补开关断言：先RED1再GREEN5，测试仅在Jenkins代理运行；不重跑真实模型主干。该检查点之后完成下述交付。


## 最终交付结果

Jenkins `deerflow-native-release` 四阶段均 SUCCESS，任务没有调用模型或自动 resume。

| 阶段 | 构建号 | 用时 | console SHA256 |
| --- | --- | --- | --- |
| 构建/5守卫/导出 | #5 | 714.951秒 | `53e24694771ef4d1ba4302da48b05a7bdd432a7795b043aa1de820b9de99ec6a` |
| 双端传输与加载 | #6 | 204.066秒 | `ac4911038db6cea19bb07f2be72755005a690aea9703c6e3f2c3301259933263` |
| 8步受控部署 | #7 | 173.383秒 | `6d406ffe9cc61ca2e1c93165f5514ea1874ffb40595b63584e452c7e51022795` |
| 独立双端就绪检查 | #8 | 14.031秒 | `94b1e46de73167cc6deb00f8841b648940da479108f7c1375fb46c1790555de7` |

Release `native-20261013-5f45039e-locked`，实际源码 `5f45039eeaff4568898d88e461be7bcac138c88c`，两端 Gateway/MCP/resident 镜像 `sha256:8c206436a47d3ee2def2721e01a11a60f5cb9e050788df168b4e33a4665a0e21`。交付包 880769024 字节，SHA `4efdeb16fdc1a55f456817da09787cb2e22b7bca3486bad91b353070dc5f1578`；交付锁 SHA `a0a4708513dc8f4e99b6e614c1318fbd05b4bc2dc53ba69c7d34017f09abbbdb`，私有 build-inputs SHA `27ccee880de1a9776282d1c5fa50da63699250f846dedaf517f19696d7cd8ffe`。schema 仍为 native0035/executor e0001。

#4 FAILURE 是新增 Jenkins 参数尚未注册，shell 缺少 LOCKED_ARTIFACT_MIRROR，退出发生在创建交付目录之前；首次声明加载后核对注册，再提交 #5。#4 console SHA `7f253d9225d06b0ceda06ea05edde7fd15de183a476eb7f598ca3386497bbb69`。原失败/ABORTED 记录保持原终态，不改写为成功。

部署只重建 Gateway/MCP/resident，PG/Redis/UI/proxy CID由部署回执核对保留。角色私有配置摘要不变，NAS保留；proxy通过nginx检查与重载、严格TLS就绪。worker仍500m/1GiB；drain=true，unreleased=0/native_active=0，专属builder已停止。

独立核对的三表历史更新前后完全一致：

| 表 | 行数 | 历史 SHA256 |
| --- | --- | --- |
| runs | 8 | `64a6d2ee3da2eb220dc1c216bd46ce49c168ad55bbaf6efa957d4025bff19a5b` |
| mcp_tasks | 4 | `e27d6a797532df7d5f4cb8a2c49cbd0d4116b887285ed84567b7fae328e08190` |
| ecs_execution_jobs | 12 | `b4f68fa45e37bba9013037d5ca40aaa646c9c70529903245bc78f890f0adda81` |

新镜像内 Playwright 1.61.0 / Chromium 149.0.7827.55 实际启动、设置并读取本地页面标题成功，Docker CLI 29.9.0。此检查无模型/外网业务调用，不扩展测试矩阵。独立证明SHA `f6b592301d96204b35b006ae7bb7911efcf3cfd9b8aa1a6cb7d2959895561479`。昨天真实销售 C→B→C 的业务验收仍见 [销售验证](ecs-native-business-sales-validation-2026-10-12.md)；今天没有重跑模型。

Jenkins完整锁、镜像包、阶段回执与独立证明保存在 `/data/jenkins-agent/deerflow/releases/native-20261013-5f45039e-locked/`，mode0700/0600。两端交付包与旧ops副本在 `/srv/deerflow-native-releases/native-20261013-5f45039e-locked/`；旧e84镜像与全部历史不删。此次只验证同schema更新/就绪；没有新增OS自动NAS启动、生产高可用或新镜像业务矩阵验收。
