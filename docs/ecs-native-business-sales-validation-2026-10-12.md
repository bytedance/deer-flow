# 上海真实销售汇总链路验收（2026-10-12）

## 结果与范围

`deerflow-native-business-sales-20261012 #3 SUCCESS`，Jenkins 总耗时 172.310 秒（包含准入检查、模型和最终 drain）。独立复核通过。本次是实际 DeepSeek、原生 API、远端 Docker worker、NAS 和认证文件下载；输入为四行示例销售数据，不是客户生产数据。没有新增测试矩阵、运行本地 Docker 或修改运行时代码。

使用恢复后的原 e84 镜像 `sha256:e84bc2845f89279aaf6d480302792461582c8eba306d79b377b5c867a7c838ae`。Controller `139.224.205.56 / 192.168.0.190`，Worker `47.117.93.194 / 192.168.0.189`。此结果不替代新交付流水线的 build/transfer/deploy 验收。

## 业务与核对

Agent 通过 `ecs_submit` 将 CSV 按地区汇总交给 B worker，当前 C 物理退出后 B 开始执行。B 完成经原生通知触发第二个 C run，读取实际 CSV 并用 `present_files` 交付。完整链路为 C→B→C，无人工创建续跑。

| 地区 | 销售额（金额单位） | CSV 金额（分） |
| --- | ---: | ---: |
| east（上海、杭州） | 2500.00 | 250000 |
| north（北京） | 900.00 | 90000 |
| 合计 | 3400.00 | 340000 |

独立按实际发布的输入 CSV 重新计算数量×单价，逐字节核对 `sales-summary.csv`。用户认证的 artifact HTTP 返回200，内容与 NAS 完全一致。原生工具调用包含 ecs_submit/read_file/present_files；目标完成并清除；通知 delivered，事件版本一致且 dispatch lease 清除；两个 Run success、三个账本工作 completed/physical_stopped，B attempt=1，同一节点。

## 本次身份与证据

- Thread：`sales-20261012-cf1ee3ee587143e99871843bb159e01b`。
- 首次 Run：`269197e7-1b70-4de7-adb4-ecee280ae70f`；自动续跑：`df0e18dd-0e25-4d4a-9a2b-5abbe84efc5d`。
- B job：`0c65b006a5fb4f87b546259ac61f422b`；MCP task：`mcp-task-62d77994339b4b6fa3aca3252881ab7b`。
- 报告 SHA256：`6b9b87f68b0e090488620d7923c75e94f99e5662072d8aa0deda0161701f8812`。
- 输入 SHA256：`ffcfc239404339d119c745b1733549bbd76fca1dcdd4655a7d97daa253b99534`。
- 主回执 SHA256：`cde5ba85a636242e415f6ae1f6af55aea62a81944efd56bb58e61c5df380f238`。
- 独立回执 SHA256：`ba772155d11c8856223ac816c085323163fab991ce792c07c3135fb2d06c1935`。
- Jenkins #3 console SHA256：`fa569b6a3761e6ce1d091c37a6f60e48c2ad6b49d2d94365776c05cf63fdf989`。

控制端 root-owned0600 回执：`/srv/deerflow-native-task6b/56636cebddc6/proof/business-sales-20261012-main.json` 与 `business-sales-20261012-independent.json`。Jenkins 专属目录 `/data/jenkins-agent/deerflow/native-business-sales-20261012` 保留版本化脚本、配置、console-1/2/3.log、business-output/v2/v3.log 和独立复核导出。用户会话和模型凭据只在控制端私有目录使用，未导出。

## 失败保留与复现边界

#1 在认证前因验收脚本的局部 urllib 导入作用域失败；只修正脚本导入。#2 在业务提交前生成76字符 thread ID，被原生64字符限制拒绝（实际 POST422）；只缩短验收标识。两次都未提交模型 Run，原版本/日志保留。#3 才是本次唯一实际模型业务链路。没有通过重跑已完成业务来修复验收包装。

成功版本输入 SHA256：business-main-v2.py `0e653550b3b01d8213b5ccefee6132a3dd17353db762008157d8e81071d4b036`；business-client-v3.py `018f49de2f976c9cdf9e17dc1da98092f909165c6c2955fcb96b3abfb9841544`；business-v3.Jenkinsfile `ac69fc33cfda1baa46bdf1ae00c8f43e58fc8212d452b00a596ae75994ffcc0e`。这些是已安装上海环境的版本化验收输入，不是通用部署入口。任务管理和 SSH 均通过 Jenkins 既有 DeerFlow 授权及 shanghai-deploy-ssh 绑定。

不要直接重建本任务或复用同名回执。再运行需新的验收标识、独立回执和正常用户登录，先核验 NAS/owner/TLS、两端健康、drain=true/unreleased=0、无原生运行与通知，再显式 resume；完成或失败后 finally drain，并核对真实终态。失败保留任务与历史，不能盲目重试或自动恢复。

## 收尾与未完成项

独立复核 drain=true、未释放工作0、非终态原生 Run0、待通知0；worker 原容器及 e84 镜像保留，healthy、无 OOM，500m CPU/1GiB。此前 BC 证明 SHA 保留。业务 Thread/文件和审计记录保留供查看。

新源码交付主干 build/export/transfer/deploy/smoke 仍未验收；NAS 自动 namespace bind、数据库时间点恢复仍未验收；GitHub/Gitee 发布继续暂停。此次成功不扩大以上结论。
