# 原生 ECS 工作池部署与恢复

更新：2026-10-12。用户已将两台上海 ECS 停机节省费用；下表公网 IP 与后文“当前安装”均是 2026-10-10 验收快照，重新开机后应重新确认公网 IP、NAS 挂载、容器与 drain 状态。这里是操作指南；此前构建过程保存在 [部署历史](ecs-native-deployment-history-2026-10-10.md)，实际运行证据见 [测试文档](ecs-native-testing.md) 和 [恢复记录](ecs-native-shanghai-resume-2026-10-10.md)。旧固定 source566/5dda 的 Shanghai build/transfer/bootstrap 脚本是历史验收输入，不能作为当前源码的冷部署入口。

| 资源 | 当前地址 / 约束 |
| --- | --- |
| Controller | `101.133.235.59` / `192.168.0.190`，2c8g |
| Worker01 | `47.103.28.252` / `192.168.0.189`，2c4g；不发布公网服务端口 |
| Jenkins | `106.14.210.163`；仅 `deerflow-shanghai-test` 管理这次验收 |
| NAS | `031sp6l7o6sh4hzha32-jow11.cn-shanghai.nas.aliyuncs.com:/` |
| 命名空间 | `task6b-native-820d7a3429d9`，两端 bind 到 `/srv/deerflow-native-test` |

B/C/BC, NAS, HTTP/WSS browser, lifecycle and same-schema rollback mains are accepted. Frozen backend composite838e is accepted with historical failures retained. Production #65, export #66, transfer #67 and installed recovery #69 SUCCESS. At the 2026-10-10 acceptance snapshot, Controller Gateway/MCP and worker resident used e84bc2845f89; all917 public runtime files match under UID1000. Database/NAS history, native0035/executor e0001 and private model/auth configuration are preserved. Admission remains drained. See [current acceptance](ecs-native-shanghai-acceptance-2026-10-10.md) and [release lock](../examples/ecs-native/deploy/shanghai-tested-release-2026-10-10.json).

操作范围：worker 的独立 installed operator CLI 已验；controller 使用宿主机受控 Compose 已验。下文通用 CLI 描述实现接口，不代表 controller installed CLI 已验收。不要在即将被停止的 resident 内执行它自身的 stop/restart。任何环境变量变化都要对指定角色执行 `up --force-recreate`，普通 `restart` 不会重新加载环境。

Gateway 或 MCP 容器重建后，必须在现有 proxy 容器内执行 `nginx -t`，成功后执行 `nginx -s reload`，再检查严格 TLS 的 `/health/ready` 和正常 owner 会话，最后启动 worker。这里的静态 `proxy_pass` 在 Nginx 加载配置时解析容器地址；只重建应用、保留代理而不 reload 会继续连接旧 IP，产生 502。重载保持代理容器、证书和配置不变。升级前先 drain 并确认 ledger/原生 Run/物理任务均已收尾，停止 idle worker resident；不要依赖出站 daemon 在控制端不可达期间自动存活。恢复保持 drain，验证两端健康后才显式 resume。

可复用同 schema 后端镜像更新入口见 [Jenkins 交付流程](ecs-native-release-ci.md)。新流程尚待开机后验证；旧固定 pin 任务仍只是历史证据。

## Images and private configuration

Build one versioned backend role image for central Gateway, ordinary B MCP and
worker resident supervision. It installs the existing locked backend environment,
PostgreSQL/Redis/browser extras and Chromium with its system libraries. Startup
runs installed Python directly, without `uv sync`. Build the existing native
frontend separately; do not substitute a historical Fleet UI image.

The runtime Dockerfile explicitly installs Debian `media-types` for native artifact MIME classification. Git belongs in the separate CI test image, where benchmark tests need version metadata; it is not added to the production role image. The currently installed Shanghai imagee84 includes the MIME packaging and focused UTF-8 source corrections. Test-tools images1e10 and4f269 are CI derivatives only; do not deploy it as a role image or treat its metadata checks as installed-role acceptance.

```bash
docker build --target native-role --build-arg UV_EXTRAS=postgres,browser \
  -f backend/Dockerfile -t deerflow-native:RELEASE .
docker build --target prod -f frontend/Dockerfile -t deerflow-native-ui:RELEASE .
docker image inspect --format '{{.Id}}' deerflow-native:RELEASE
```

Select immutable IDs locally or registry `name@sha256:digest` for deployment. The
Dockerfile permits explicit `PYTHON_IMAGE`, `DOCKER_CLI_IMAGE` and `UV_IMAGE`
mirror/cache selectors. Record their immutable digests and actual distribution;
changing to `python:3.12-slim` can select Trixie and is not Bookworm acceptance.
Existing no-target production builds
continue to select the original runtime; the role image requires its explicit target.

`.dockerignore` excludes `.env*`, runtime configs/data, private/operator
directories, keys, logs and acceptance output. Keep all actual private material
outside the checkout/build context in an owned mode-0700 directory. Never print
`docker compose config`, image/container environment, raw logs or private URLs.

Before generation, mount NAS at the same **absolute path** on controller, worker
and all DooD containers. Provision `pool/pool-mount-id` once on the verified mount,
with a shared immutable operator marker. Production preflight requires a mounted
filesystem and matching marker; it never creates a fallback directory. An owned
local fixture may explicitly use `--owned-local-fixture` as a NAS stand-in.

```bash
python3 scripts/ecs_native.py generate \
  --private-dir /private/operator/native --nas-root /mnt/deerflow \
  --central-url https://gateway.example --node-id ecs-one --owner NATIVE_OWNER_ID \
  --image sha256:ROLE_IMAGE_ID --project deer-native --sandbox-prefix deer-native-one \
  --browser
backend/.venv/bin/python scripts/ecs_native.py preflight \
  --config /private/operator/native/controller-ops.json
```

Run generation separately in the public checkout on each Docker host; `compose_file` in each generated operations file must resolve to that host's actual absolute Compose path. Generation creates exclusive mode-0600 JSON files containing environment
references, no credentials. Supply separate mode-0600 `controller.env` and
`worker.env` using the reference templates in `examples/ecs-native/deploy/`.
Obtain the real native owner ID through normal authentication; the ordinary MCP
`user_auth` and `user_profiles` must bind that same owner. Shared node token, JWT
secret, internal auth token and scope signing secret must agree across peers.
Keep discovery and owner credentials distinct. Do not source/eval env files;
Compose reads them as data, and CI/operator commands receive secrets from their
private environment. The worker has native DB access but **no executor DB URL**.
Operator drain commands use a separate trusted operator environment containing
`ECS_EXECUTOR_DATABASE_URL` and `ECS_NATIVE_METADATA_DATABASE_URL`.

Both private Gateway configs enable native Scheduler foreground tools/completion,
shared memory facts and instance-local memory indexes. Browser tools/provider are
optional at generation but included with `--browser`. `remote_all: true` queues
ordinary interactive native runs on the existing fixed worker even when browser
is disabled; the controller needs no Docker socket. The default native host
behavior outside this explicit operator policy stays unchanged.

## Capacity, TLS and private network

The fixed worker is 2 CPU / 4 GiB, `max_concurrency=1`. Its resident container
runs native Uvicorn and the existing outbound B daemon together under actual
`cpus: 0.5`, `mem_limit: 1g`. Thus B polling overhead cannot escape resident
accounting. Native warm AIO reserves 1 CPU / 1 GiB continuously. C reserves a
virtual 500m / 1 GiB until all native finalizers complete. B has at most the
remaining 500m / 1 GiB, network none and a non-root user. Both share one SQL
ledger; unknown physical work never releases capacity on lease expiry.

The worker publishes **no port**. Its internal native Gateway binds loopback;
all control/report/browser connections originate outbound. It needs private
native PostgreSQL, authenticated Redis and the same NAS mount. The controller
Compose publishes PostgreSQL/Redis only with an explicit bind host (loopback by
default). For real peers set a specific private interface and firewall TCP
5432/6379 to that worker only. PostgreSQL roles/SSL, Redis TLS or protected VPC
transport, NAS mount options/locking/durability and private routing require the
cloud operator's review. No cloud/firewall command is executed by these files.

TLS ingress carries native `/api/*`, `/api/langgraph/*`, native browser WSS and
`/execution/*` ordinary B MCP/dispatch. Supply trusted `tls.crt` / `tls.key` in
the private directory. Worker TLS verification is mandatory. Owned private-CA
fixtures may set `SSL_CERT_FILE=/run/operator/ca-bundle.crt` to the system public CA bundle plus the owned CA, preserving model-provider HTTPS trust. A direct owned-health probe may use the owned `ca.crt`; no insecure production
flag is provided. Nginx overwrites forwarding headers and passes Upgrade /
Connection. Uvicorn trusts only the fixed proxy IP, reconstructing actual `wss`
for worker tunnels. Original native Cookie/Auth/Host/Origin/owner checks remain
in both peers. Default Docker subnet `172.29.61.0/24` avoids the known
`192.168.0.0/16` VPC; change `ECS_CONTROL_SUBNET` and `ECS_PROXY_IP` together if
local routing requires another non-overlapping range. Do not use wildcard proxy
trust or expose the internal Gateway/MCP listeners.

DooD uses `DEER_FLOW_SANDBOX_HOST=host.docker.internal` and `host-gateway` on the
worker. Existing native Linux behavior binds its AIO host API to the Docker
bridge address; Desktop uses loopback. Do not bind unauthenticated AIO to 0.0.0.0.
The native memory index volume is local to each role and stays outside shared NAS.

## First startup and normal lifecycle

Use the exact project/env/Compose selectors from the generated operations file.
For a fresh owned DB only, first start controller `postgres redis`, then run the
explicit executor schema command as a one-off using the same role image:

```bash
docker compose --project-name deer-native-controller \
  --env-file /private/operator/native/controller.env \
  -f examples/ecs-native/deploy/controller.compose.yaml up -d postgres redis
docker compose --project-name deer-native-controller \
  --env-file /private/operator/native/controller.env \
  -f examples/ecs-native/deploy/controller.compose.yaml run --rm --no-deps mcp \
  python -m ecs_executor.schema upgrade
```

Set `ECS_ROLE_IMAGE`, `ECS_PRIVATE_DIR` and `ECS_NAS_ROOT` to the reviewed private
selectors for those first Compose commands. These are data selectors, not secret
values. New PostgreSQL bootstrap creates distinct `deerflow` and
`deerflow_execution` databases. Existing databases need an explicit operator
migration/backup review; never reuse the native DB as the executor ledger.
Native startup performs its existing migrations and preactivation legacy
quarantine; see `ecs-native-fork-integration.md` before enabling old fork data.

```bash
backend/.venv/bin/python scripts/ecs_native.py start --config /private/operator/native/controller-ops.json
backend/.venv/bin/python scripts/ecs_native.py start --config /private/operator/native/worker-ops.json
backend/.venv/bin/python scripts/ecs_native.py resume --config /private/operator/native/worker-ops.json
backend/.venv/bin/python scripts/ecs_native.py drain --config /private/operator/native/worker-ops.json
backend/.venv/bin/python scripts/ecs_native.py status --config /private/operator/native/worker-ops.json
backend/.venv/bin/python scripts/ecs_native.py stop --config /private/operator/native/worker-ops.json
backend/.venv/bin/python scripts/ecs_native.py restart --config /private/operator/native/worker-ops.json
```

The lifecycle commands above require an installed backend Python environment, including SQLAlchemy/psycopg; they do not work in bare host Python. Run worker commands from an independent trusted operator process/one-off container on its Docker host, with the separate trusted operator ledger
environment. Drain sets `operator_drain` in the existing node JSON under the same
advisory transaction as B/C claims. Both service initializations preserve it;
worker reports/recovery continue. New native intents can remain durably queued;
they are not silently replayed or cancelled. Status prints only the fence and
unreleased count. Stop refuses until all assigned reservations report physical
STOP after native finalizers, and refuses any remaining node-owned B containers.
Then resident processes stop with 240-second outer grace. Uvicorn request drain
is bounded to 10 seconds, leaving time for the Gateway service lifespan (71
seconds), native host quiesce (120 seconds) and shutdown slack. Exact labeled/prefix
owned idle warm AIO is stopped and removed, and absence is checked. There is no
force switch, prune, lease clearing, SQL state patch or volume destruction.
Uncertain physical work requires recovery through its normal native/worker
owner; it is not an idle success. Restart preserves drain. Explicitly resume
only after controller, worker bootstrap and protected TLS are healthy.

Keep the controller serving until worker reports/cleanup finish. Controller
stop additionally refuses any active/pending native Run; queued intents must
settle through normal native APIs before controller shutdown. It stops only
Gateway/MCP/frontend/proxy, retaining PostgreSQL/Redis and every volume. The
small supervisor stops its sibling on unexpected child exit but never clears
an assignment or reports physical STOP; crash recovery retains reservations.

## Version rollback

Rollback is a stopped-writer generation restore, not an Alembic downgrade.
Retain the previous immutable role image, current native frontend image, coherent
private config/secrets, native DB, executor DB and NAS backup generation. Drain,
finish native finalizers/worker cleanup, stop worker roles, fence public ingress
and stop controller roles. Verify owned physical containers are absent. Preserve
both DB backups plus NAS revision/locking state together. Restore only an
explicitly reviewed generation with a compatible native schema and executor
revision; never start an old binary against an unknown/newer schema.

A private mode-0600 manifest has `image`, `native_revision`, `executor_revision`,
`generation`, `config_sha256`. The last is `config_fingerprint(config)` over the
six private role JSON files plus that role's env file. The operator selects it:

```bash
backend/.venv/bin/python scripts/ecs_native.py select-version \
  --config /private/operator/native/worker-ops.json \
  --manifest /private/operator/previous.manifest.json
```

Selection checks the actual executor/native schema, config fingerprint, drain,
reservation/physical absence and stopped project, then atomically replaces only
the private image selector. It does not restore databases/NAS or destroy data.
Start the coherent selected roles, verify readiness/TLS/browser and then resume.
Shanghai #48 verified same-schema52ce→a216→52ce selection/restoration, preserving DB/NAS/config/history. Worker installed selection and controller guarded host selection were exercised. This does not verify controller installed CLI, database point-in-time restore or OS reboot. The dedicated Jenkins test task owns further authorized verification.
Remote Git publication remains paused; the historical Fleet publish task is not
used for this native deployment.


## NAS 恢复和启动顺序

两端先验证原 NFS4 挂载及 namespace marker，再恢复 bind。此步骤在重启后需要人工执行；未验收开机自动 NAS 恢复，验收脚本未执行 OS/ECS 重启；此前用户停机再开机后的 bind 恢复仍按这些步骤人工验证。

```bash
test "$(findmnt -n -o FSTYPE --target /srv/deerflow-data)" = nfs4
test "$(findmnt -n -o SOURCE --target /srv/deerflow-data)" = \
  '031sp6l7o6sh4hzha32-jow11.cn-shanghai.nas.aliyuncs.com:/'
test "$(cat /srv/deerflow-data/task6b-native-820d7a3429d9/pool/pool-mount-id)" = 820d7a3429d9
test -d /srv/deerflow-native-test
mountpoint -q /srv/deerflow-native-test || \
  sudo mount --bind /srv/deerflow-data/task6b-native-820d7a3429d9 /srv/deerflow-native-test
mountpoint -q /srv/deerflow-native-test
```

随后验证私有配置0700/文件0600、两端相同 marker、严格 TLS、原数据库和卷。保持 drain，先启 controller 的 PG/Redis，再启 controller 应用、worker resident。两端 ready 且没有未确认的物理工作后，才显式 resume。普通恢复不重新初始化 owner、不迁移回旧 schema、不修改 ledger 历史、不删除数据库或 NAS。

首次部署空数据库与日常恢复是不同流程。当前上海已经完成初始化，日常恢复必须保留已有 owner 与私有配置。

首次部署的顺序：

1. 在每台 Docker 宿主机的公开 checkout 运行 `generate`，使用实际绝对路径。若尚无 owner，可用单独的占位 UUID 引导配置，但保持 drain，不执行任务；占位 UUID 不是真实用户授权。
2. 启 PG/Redis，再用 MCP one-off 执行上文 executor `schema upgrade`。启动正常 controller Gateway，由其原生 `bootstrap_schema` 完成 native 新库 `create_all + stamp head` 或已有 managed 库升级。没有独立 `make migrate`；不能用裸 `alembic upgrade head` 代替新库 bootstrap。
3. 通过受保护的 PostgreSQL 管理输入创建一次 `gateway LOGIN`，密码仅 stdin/私有文件，不放命令参数。沿用已验证的 session 日志保护：先 `SET log_statement='none'`、`SET log_min_error_statement='panic'`、`SET log_min_duration_statement=-1`，再事务创建和授权，避免失败 SQL 将密码写入数据库日志。它只能连接 `deerflow`；撤销 `deerflow_execution` 的 PUBLIC CONNECT。对 native public schema 授予 USAGE/CREATE、表 SELECT/INSERT/UPDATE/DELETE、sequence USAGE/SELECT/UPDATE，并对 postgres 创建的未来表/sequence 设置相应 default privileges。已有 gateway 角色拒绝重建；恢复不重新执行这些初始化 SQL。worker env 只保留 native DB URL，不传 executor DB 管理凭据。
4. 通过正常前端初始化向导，或 `POST /api/v1/auth/initialize`（email/password/remember_me）建立真实 owner。201 的 `id` 是 UUID；409 表示已初始化，应登录原账号 `/api/v1/auth/login/local` 后读取 `/api/v1/auth/me`，不能新增管理员或改 SQL。请求使用严格 CA/Origin，session 和 CSRF cookie 保存在私有文件。
5. 将真实 owner UUID 绑定到 `executor.json` 的 `user_profiles`、`user_credential_env` 以及 `extensions.json -> mcpServers.ecs.user_auth.users`；其值仍是独立凭据的环境引用。将最小已绑定配置同步给 worker，保留 native mcp_tasks/task_toolsets/interceptor 完整配置。不要复制 controller 整份 env 或管理员数据库密码给 worker。
6. 使用相同不可变镜像，先 force-recreate controller Gateway/MCP，再启动 worker resident。设置 `GATEWAY_CORS_ORIGINS` 为真实 TLS 入口的 Origin，校验 private CA、CORS、owner map、两端 ready 和 drain/idle 后显式 resume。模型 key 从私有环境引用提供，不写进源码或镜像。

首次冷部署入口为通用 Compose + `generate`/schema/operations，历史 Shanghai 固定 pin 脚本仅记录此前验收。最终 release 的源码、镜像和 schema 以独立交付锁为准。

## 本次上海已安装环境重新拉起

先完成上文两端 NAS 和 bind/marker 检查。以下命令只使用已保留的私有配置与不可变镜像，不重建用户、数据库或历史。镜像归档还保存在 Jenkins 的 `/data/jenkins-agent/deerflow/native-task6b-56636cebddc6/transfer/production-repaired-contract-c6af94a95ae7-image.tar` 及两台 ECS 的 `/srv/deerflow-native-task6b/56636cebddc6/received/`；加载前核对 release JSON 的 SHA256。

Controller 执行：

```bash
DEER_NATIVE_ROOT=/srv/deerflow-native-task6b/56636cebddc6
DEER_NATIVE_PRIVATE="$DEER_NATIVE_ROOT/private/820d7a3429d9/resident"
docker compose --project-name deer-native-820d7a3429d9-controller \
  --env-file "$DEER_NATIVE_PRIVATE/controller.env" \
  -f "$DEER_NATIVE_ROOT/source/examples/ecs-native/deploy/controller.compose.yaml" \
  up -d --no-build --pull never --wait --wait-timeout 180 \
  postgres redis gateway mcp frontend proxy
docker exec deer-native-820d7a3429d9-controller-proxy-1 nginx -t &&
  docker exec deer-native-820d7a3429d9-controller-proxy-1 nginx -s reload
curl --fail --cacert "$DEER_NATIVE_PRIVATE/ca.crt" \
  https://192.168.0.190:2026/health/ready
```

Controller 严格 TLS 健康检查成功后，在 Worker 执行：

```bash
DEER_NATIVE_ROOT=/srv/deerflow-native-task6b/56636cebddc6
DEER_NATIVE_PRIVATE="$DEER_NATIVE_ROOT/private/820d7a3429d9/resident"
docker compose --project-name deer-native-820d7a3429d9-worker \
  --env-file "$DEER_NATIVE_PRIVATE/worker.env" \
  -f "$DEER_NATIVE_ROOT/source/examples/ecs-native/deploy/worker.compose.yaml" \
  up -d --no-build --pull never --wait --wait-timeout 180 resident
```

这是已安装环境的恢复入口，首次空库部署仍遵循前述初始化流程。当前保持 drain；需要接收任务时，按上文可信 operator 流程核对 owner、schema、两端 ready/idle 后显式 resume。控制端升级重建前先 drain/idle 并停止 worker，再按重载代理、启动 worker 的顺序操作。

## 验收和复验

| 已验证范围 | Jenkins 证据 |
| --- | --- |
| B 任务主干和正常清理 | #24 实际主干 PASS；#26 清理 SUCCESS |
| C 原生模型/工具及 NAS 输出 | #29 SUCCESS |
| C→B→C 同 goal 自动续跑 | #35 实际主干 PASS；#36 只读证据 SUCCESS |
| worker CLI / controller host Compose 启停 | #38 SUCCESS |
| 浏览器 JPEG/严格 WSS/同会话重连/正常退役 | #46 SUCCESS |
| 同 schema 版本往返恢复 | #48 SUCCESS |
| UTF-8、MIME、CI 与既有测试修复 | #53/#56/#59 focused PASS; #60-#64 honest composite accepted; #65 production and #69 installed recovery SUCCESS |

不因为文档整理而重复模型主干。复验先检查 ready、drain 和资源状态，再根据实际故障选择已有主干脚本。旧失败构建及收据保留在历史记录，不替换为成功结果。
