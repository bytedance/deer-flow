# Tasks

- [x] 1. Separate accepted runtime snapshot (1558a120) and historical evidence snapshot (b1ee35c7); preserve 67 original input hashes.
- [x] 2. Implement immutable build/export/transfer and guarded same-schema rollout with per-step receipts and no automatic resume.
- [x] 3. Document private inputs, recovery, scope boundaries and historical/current entry distinctions.
- [x] 4. Complete Ruff/format, Python compilation, shell syntax, OpenSpec strict validation and 67 historical hashes; preserve the delivery implementation in a separate local commit. Its commit identity is recorded in the private resume checkpoint.
- [ ] 5. After user starts Shanghai ECS, recover existing mounts/services and run five guard tests plus one Jenkins delivery main; then one chosen real workflow smoke.

Implementation is prepared; cloud delivery validation remains pending. Remote Git publication remains paused.

2026-10-12 cloud checkpoint: guard #3 SUCCESS (5 cases, 0.018s); original #1/#2 workspace/@tmp failures retained. Recovery #2 SUCCESS after correcting read-only runs.run_id audit; #1 retained. NAS binds, original e84 container IDs, private fingerprints, native0035/executor e0001 and three-table history hashes preserved; strict TLS, worker500m/1GiB and drain/unreleased0 verified, no model calls. Prepared-checkout entry passes actual Jenkins Groovy validation. Task5 still awaits new build/transfer/deploy/readiness. One real workflow completed subsequently as recorded below.

2026-10-12 business checkpoint: deerflow-native-business-sales-20261012 #3 SUCCESS, 172.310s; one actual DeepSeek C→B→C sales-CSV workflow, authenticated output200, independently recalculated total340000 cents. Two native Runs success, B attempt1, all three jobs physically completed, automatic delivered notification, goal cleared. Final drain/unreleased0 and original e84 worker healthy500m/1GiB verified. #1/#2 failed before business admission (validation-script import scope / 76-char thread ID exceeding native64); failures retained. No model replay, runtime patch or expanded matrix. Independent receipt ba772155d11c8856223ac816c085323163fab991ce792c07c3135fb2d06c1935. Task5 stays unchecked pending the new delivery main.

2026-10-13 checkpoint: controller101.132.36.217 / worker139.196.37.75, private identities and trusted keys unchanged. Fresh recovery job #1 SUCCESS,127.360s, original roles/config/history retained, drain/unreleased0, strict TLS. Release #1 FAILURE at Docker Hub metadata timeout; 5 guards passed. Dedicated builder mirror verified/applied without changing daemon/other projects. Release #2 reached APT downloads but was normally ABORTED after throughput measured10x slower than the previously used mirror. Exact original builder manually stopped after terminal confirmation; cache/artifacts retained. Minimal APT_MIRROR forwarding fix: existing5 guards expected RED1 then GREEN5 under Jenkins agent account; lint/format clean. New committed delivery build still to run; runtime remains original e84, no new model main.


2026-10-13：release #3 的原生 Python 包直连持续慢下载；构建容器同一 Playwright wheel 样本，直连393216字节/17.65秒后超时，既有清华源2097152字节/1秒。仅正常停止本项目 #3（ABORTED）并核对确切 builder CID 后停止；缓存及失败证据保留。入口新增 `--locked-artifact-mirror` / Jenkins `LOCKED_ARTIFACT_MIRROR` 布尔开关，透传既有 Dockerfile 固定 `UV_ARTIFACT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/pypi/web`；不新增任意URL输入，不改变依赖版本、SHA、大小或锁文件恢复校验，选定布尔值写入build-inputs摘要。原5守卫内补开关断言：先RED1再GREEN5，测试仅在Jenkins代理运行；不重跑真实模型主干。新镜像交付仍待完成。
