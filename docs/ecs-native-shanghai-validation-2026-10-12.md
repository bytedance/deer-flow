# 上海开机恢复与新交付验证（2026-10-12）

Controller：139.224.205.56 / 192.168.0.190；Worker01：47.117.93.194 / 192.168.0.189。经保留的 host key 核对，原主机身份、e84 镜像和容器都保留。首次检查时 NFS 已挂载、namespace bind 缺失、角色容器均停止。

## 已完成

- `deerflow-native-release-guards #3 SUCCESS`：原定 5 个标准库守卫用例全部通过，测试时间0.018秒。#1/#2 是工作目录及同级 @tmp 创建权限失败，未执行用例；失败日志保留。只预建 DeerFlow 专属目录 uid999/gid987/mode0700，未改公共父目录权限。
- `deerflow-native-recovery #2 SUCCESS`：验证原 NFS4/source/marker，在空目标目录恢复两端原 namespace bind，启动原 PG/Redis、Gateway/MCP/UI/proxy，校验并重载原代理，严格 TLS 成功后启动原 worker。容器身份、私有配置 fingerprint、runs/mcp_tasks/ecs_execution_jobs 历史摘要保留。native0035/executor e0001 正确，worker500m/1GiB，drain=true/unreleased=0。
- 恢复 #1 FAILURE 保留：两端 bind 已完成，控制端 PG/Redis 健康；审计 SQL 误按 runs.id 排序，而原生主键是 run_id。只读复现并核对字段后，#2 从 base 检查点继续，没有重放挂载。无业务表修改或模型调用。
- 支持已准备干净 Git bundle checkout 的正式 Jenkinsfile 已通过真实 Groovy 校验，仍须匹配完整源码 commit。

| 证据 | SHA256 |
| --- | --- |
| 守卫 #3 console | e297392a77774b199ed629f7bcd68b919d2e69b5a951e8e2013894e502471fea |
| 恢复 #1 console | 683857891074a79b4c9b876725fee7538992f986be8e73b03147d589e3b11cf1 |
| 恢复 #2 console | 1a58ca9202bb4e0877f49f05e569e870860815ea40d4a243e110797570fe5558 |
| 最终恢复回执 | 2a2ed39d6f4fb95b07155e36f28a08341cfab267f2f11960a8effa08d25cbe2c |

回执：Jenkins `/data/jenkins-agent/deerflow/native-release-recovery-20261012/proof-v2/recovery.json`。原始失败、各阶段及 v2 回执均保留。

## 当前边界

以上证明原 e84 环境的开机后人工恢复与 5 个交付守卫，尚不代表新镜像 build/transfer/deploy/smoke 全部通过。应用户要求，先完成唯一真实销售 C→B→C 业务冒烟（见下文），新交付主干仍待验证；不重跑此前完整 B/C/BC 矩阵。NAS 自动 bind、数据库时间点恢复仍未验收。远程 Git 发布仍暂停。

## 唯一真实业务链路已通过

`deerflow-native-business-sales-20261012 #3 SUCCESS`，172.310秒。实际 DeepSeek→普通 MCP B→通知自动续跑 C，四行示例销售 CSV 汇总并原生交付；合计3400.00，认证 HTTP200与 NAS 逐字节一致。两个 Run成功、三个工作物理完成、B attempt=1。独立复核通过，最终 drain=true/unreleased=0，worker原容器/e84健康、500m/1GiB。#1/#2为模型提交前的验收脚本导入/标识长度失败，原日志保留；没有重复实际模型业务。

详见 [销售汇总业务验收](ecs-native-business-sales-validation-2026-10-12.md)。独立回执SHA `ba772155d11c8856223ac816c085323163fab991ce792c07c3135fb2d06c1935`。后续剩余交付主干 build/transfer/deploy/smoke，远程 Git 发布仍暂停。
