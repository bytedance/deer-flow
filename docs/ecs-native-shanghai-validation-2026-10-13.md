# 上海恢复与交付验证（2026-10-13）

Controller101.132.36.217 / 私网192.168.0.190；Worker139.196.37.75 / 私网192.168.0.189。原 host key、实例身份、NAS 和 e84 镜像保留。

- 独立 deerflow-native-recovery-20261013 #1 SUCCESS，127.360秒。两端原 NFS 已挂载、namespace bind缺失；恢复原 bind和容器，严格 TLS、配置 fingerprint、三表历史摘要保留；drain=true/unreleased=0，无模型调用。回执SHA ae1b2c14dd603b31b97957fc8833d2028c7d5c491f2103c5595cb565209f6445；consoleSHA fb5c99e1db644d014da9427e5981c159e6e5a019de4d5bd1536b0a547a617ce6。
- 新任务 deerflow-native-release #1 FAILURE，源码6131c0f2，原5守卫通过0.028秒；隔离 BuildKit 未继承daemon镜像源，Docker Hub metadata直连超时。consoleSHA671ae7e2c3d2277a69b66f66b01da1243bb7ff28419ac4418da79ae5e1f2855a。保留 native-20261013-6131c0f2 目录。
- 验证既有镜像源实际manifest后，只在原专属停止中的 builder 添加 docker.io mirror=docker.m.daocloud.io。原CID与1CPU/3GiB/零swap预算不变，配置SHA209dc1f2a8bc843048f73f5168d1c9d5f533e6046cd96a39c5d2662cfaf9b640。
- #2 使用新目录 native-20261013-6131c0f2-mirror，基础镜像加载成功并进入APT安装。256KiB实际索引样本：Debian16.38秒，既有清华源1.66秒。因新CLI遗漏已有APT_MIRROR透传，正常停止该构建并保留cache/log。终态ABORTED；Jenkins进程组终止使finally未完成，核对原CID后手工停止builder，没有停止其他容器。
- 修复仅透传Dockerfile已有APT_MIRROR；验证DNS主机名输入并保存build-inputs摘要到镜像标签。现有5守卫内补断言，不增加用例数量：Jenkins代理账户 RED1（SHA49595c710733f85c1486797fdb65015b8fe47a0e86db9a1e436264e48b76528a），随后 GREEN5（0.025秒）；Ruff检查及格式通过。
- 已准备两个DeerFlow文件凭据，分别存放非秘密环境清单与受信known_hosts；原SSH凭据保持不变。清单SHA17392c5a173c6c6b99ffeae03d4568a42b7028d1e7b13ebf47481a0eae60f937，绑定实际两端路径、私有配置/Compose摘要、原e84和独立UI镜像。generation沿用已验收兼容类；不声称新增数据库备份或PITR。

证据留在 Jenkins /data/jenkins-agent/deerflow/native-release-recovery-20261013，既有昨日业务证明/文件和失败历史未覆盖。昨天真实销售C→B→C已通过，本轮不重跑模型矩阵。当前角色仍是原e84，新构建/传输/部署/交付smoke未全部通过，远程Git发布暂停。


2026-10-13：release #3 的原生 Python 包直连持续慢下载；构建容器同一 Playwright wheel 样本，直连393216字节/17.65秒后超时，既有清华源2097152字节/1秒。仅正常停止本项目 #3（ABORTED）并核对确切 builder CID 后停止；缓存及失败证据保留。入口新增 `--locked-artifact-mirror` / Jenkins `LOCKED_ARTIFACT_MIRROR` 布尔开关，透传既有 Dockerfile 固定 `UV_ARTIFACT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/pypi/web`；不新增任意URL输入，不改变依赖版本、SHA、大小或锁文件恢复校验，选定布尔值写入build-inputs摘要。原5守卫内补开关断言：先RED1再GREEN5，测试仅在Jenkins代理运行；不重跑真实模型主干。新镜像交付仍待完成。
