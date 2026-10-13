# 上海原生 ECS 工作池验收结果

更新：2026-10-12。本页记录 2026-10-10 的验收快照；用户随后关闭两台上海 ECS，表中公网 IP、容器状态和 drain 数值不代表当前在线状态。重新开机须重新核实。此次重做已完成实现、主干验收和最终镜像安装。两种路线共存：B 运行持久程序任务；C 在 worker 运行原生 DeerFlow Agent；C 可提交 B 并在结果回流后继续同一个原生目标。

| 验收范围 | 实际证据 |
| --- | --- |
| B 持久任务、文件交付、正常清理 | #24 实际主干通过；#26 清理成功 |
| C 原生模型/工具/Run、NAS 文件交付 | #29 SUCCESS |
| C→B→C 同目标自动续跑 | #35 实际主干通过；#36 独立只读核验 SUCCESS |
| worker installed CLI / controller host Compose | #38 SUCCESS；停止、启动、重启和数据保留 |
| 浏览器 HTTP / 严格跨机 WSS / 同会话重连 / 退役 | #46 SUCCESS；零模型调用 |
| 同 schema 兼容镜像往返恢复 | #48 SUCCESS；数据库、NAS 和历史保留 |
| 最终后端代码验收 | #60–#64 不可变证据组合；Ruff、默认套件完整分片或通过子集加原整文件修复、blocking-I/O 229 passed |
| 最终生产镜像 | #65 SUCCESS；917 个公开源文件匹配，UID1000，MIME 正确，无 CI Git/make |
| 镜像导出和双端加载 | #66 / #67 SUCCESS；相同镜像 ID 与归档哈希 |
| 最终安装与连接恢复 | #68 FAILURE 保留；#69 SUCCESS，现有代理重载、worker 切换及最终核验通过 |

最终后端验收使用诚实的组合证据：失败分片中的已通过子集、#62 完整第三分片和第四分片已通过子集，加 #62/#64 原整文件修复。#61 blocking-I/O 为229 passed。历史 #60/#61/#62/#63 的失败、超时及原始日志均保留；没有把失败构建改成通过，也不宣称重新跑过一套全部成功的完整套件。详见 [测试文档](ecs-native-testing.md)。

#68 的失败来自代理静态解析的上游容器地址过期：控制端已安装并健康，但外部健康端点返回502，worker尚未刷新。恢复在核对历史和配置备份后，仅对现有代理执行 nginx 校验/重载，再刷新 worker；未重建控制端、数据库、Redis、前端或代理容器，未调用模型或重新跑主干。

| 2026-10-10 验收时运行项 | 值 |
| --- | --- |
| Controller | 101.133.235.59 / 192.168.0.190，2c8g |
| Worker01 | 47.103.28.252 / 192.168.0.189，2c4g |
| Jenkins | 106.14.210.163，专属任务 deerflow-shanghai-test |
| 最终 backend role image | sha256:e84bc2845f89279aaf6d480302792461582c8eba306d79b377b5c867a7c838ae |
| 原生数据库版本 | 0035_native_fork_compatibility / alembic_version |
| 执行账版本 | e0001_execution_ledger / ecs_executor_alembic_version |
| Worker resident 限额 | 500m CPU / 1GiB 内存 / 2GiB memory+swap |
| 准入状态 | drain=true，unreleased=0；暂不接收新任务 |
| NAS | 031sp6l7o6sh4hzha32-jow11.cn-shanghai.nas.aliyuncs.com:/ |
| NAS namespace | task6b-native-820d7a3429d9 → /srv/deerflow-native-test |

源码冻结 ID：c6af94a95ae710b273ad2f07385beaa756f0c85e29f2e558eb92dee0f34da137。
源码归档 SHA256：e40428adefee18821b93104b5215852521b3555a390ad02531049ba2fa80b1a4。
源码 manifest：33078fa2fb16f7e7f5cbc6c96ecce3bf644f9298745b94efae0d64908ae09f1b。
镜像归档 SHA256：3534a12756038a388d732a4e9a2abcbd6098d50e070b7eebe938fe153d0fb9d3（804700672 bytes）。
最终恢复回执 SHA256：72e3327ecc4fd677dc621cc9bca5b4d41fef314e519f5afe71afbc51d71e6206。
完整公开交付锁见 [release JSON](../examples/ecs-native/deploy/shanghai-tested-release-2026-10-10.json)。

源码归档是冻结时的不可变内容；后续补充的验收与操作文档不反写归档。前端沿用独立验收的原生 UI 镜像 d302f8c890fbb3259f633fe38244d841f8614016cdf77818660d7bf949bb46de，其历史源包566/e27独立记录，不归为c6af的前端构建。

后续重新拉起按 [部署与恢复指南](ecs-native-deployment.md) 操作，先验证 NAS 挂载/marker、私有配置和两库版本，保持 drain，控制端健康及代理重载后再启动 worker，核验后显式 resume。首次空库部署另按该指南的 schema bootstrap 和正常 owner 初始化流程，不能重用历史固定 pin 脚本当作当前冷部署入口。

已验操作范围是 worker 独立 installed operator CLI 与 controller 宿主机 Compose。controller installed CLI、OS/ECS 重启后的自动 NAS bind、数据库时间点回退未验；NAS bind 重启后仍需按文档人工恢复。原生 Scheduler 和记忆有前期独立验收，未把这次镜像安装核验扩展为新的云端全矩阵测试。GitHub/Gitee 发布仍暂停。
