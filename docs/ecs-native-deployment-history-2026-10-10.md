# Historical deployment checkpoints — superseded operational guide

This file preserves the original deployment log. Its addresses, source/image pins and pending statements describe their checkpoint only. Use [the current deployment guide](ecs-native-deployment.md) for operations.

# Native fixed-node operations (Task6B)

Current Shanghai acceptance (2026-10-10): controller `101.133.235.59` / private `192.168.0.190`; worker `47.103.28.252` / private `192.168.0.189`. Admission is drained; the current installed role image is browser derivative `52ce23272ed5…` (base publication a216). Historical statements below describe their recorded checkpoint, not the current state.

| Scope | Current result |
| --- | --- |
| B ordinary MCP infrastructure | Main passed; #24 wrapper failed, #26 normal native cleanup succeeded |
| C native remote tool and NAS delivery | #29 SUCCESS; native bash/read_file/present_files, ledger physical STOP and shared output verified independently |
| Native goal C → B → C | Actual installed main PASS in #35; its terminal-notification lease assertion caused wrapper FAILURE. #36 read-only verification SUCCESS, with automatic continuation, goal clear, delivery and physical STOP verified |
| Native browser HTTP / cross-host WSS control | #46 SUCCESS: JPEG delivery, strict WSS input, same-session reconnect and normal retirement; zero model calls |
| Installed lifecycle / remaining operations | #38 SUCCESS: worker native CLI stop/start/restart, controller host Compose stop/start, history/volumes preserved. Same-schema rollback #48 SUCCESS/restored; controller CLI, reboot/final gates and coherent cold bundle pending |

The selected original DeepSeek subset is now provisioned privately and was used for #27, #29 and the #30 and #35 native BC trials. No credential value is included in these documents or immutable images.

These files describe the native B/C deployment, not the retired Fleet runtime.
Shanghai cloud testing and the dedicated Jenkins test task are now authorized.
Jenkins build #8 verified the complete source, shared NFS and actual builder
cgroup limits, then failed at public registry base metadata timeout. Installed
roles, cross-host WSS and functional B/C acceptance
remain pending. Evidence is recorded in `ecs-native-testing.md`; protocol/static
tests do not constitute deployed acceptance.

## Images and private configuration

Build one versioned backend role image for central Gateway, ordinary B MCP and
worker resident supervision. It installs the existing locked backend environment,
PostgreSQL/Redis/browser extras and Chromium with its system libraries. Startup
runs installed Python directly, without `uv sync`. Build the existing native
frontend separately; do not substitute a historical Fleet UI image.

The runtime Dockerfile explicitly installs Debian `media-types` for native artifact MIME classification. Git belongs in the separate CI test image, where benchmark tests need version metadata; it is not added to the production role image. The currently installed Shanghai image52ce predates this packaging correction and the focused UTF-8 source fix. Test-tools image1e10 is a CI derivative only; do not deploy it as a role image or treat its metadata checks as installed-role acceptance.

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
The local bounded recovery used the cached Linux Docker CLI from
`deerflow-bc10:worker-mixed-current-p1-v2` solely as a binary-copy source; neither
its application files nor its installed dependency environment is imported.
The first build failed Docker Hub token resolution; the cached-base attempt then
failed a Debian HTTP package index. HTTPS indexes recovered that observed
failure. The subsequent build completed APT/Node/Lark but was stopped after a
locked-wheel download stage stayed unchanged for over ten minutes. BuildKit
cache remains. A subsequent bounded Docker probe fetched an exact locked wheel
over verified HTTPS (200, 1,024 bytes, 2.69 seconds); the earlier failure did not
reproduce. Dependency transport defaults to four concurrent downloads and a
30-second HTTP timeout, scoped to locked `uv sync` only. A successful role build
and installed main still require evidence. Existing no-target production builds
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
backend/.venv/bin/python scripts/ecs_native.py generate \
  --private-dir /private/operator/native --nas-root /mnt/deerflow \
  --central-url https://gateway.example --node-id ecs-one --owner NATIVE_OWNER_ID \
  --image sha256:ROLE_IMAGE_ID --project deer-native --sandbox-prefix deer-native-one \
  --browser
backend/.venv/bin/python scripts/ecs_native.py preflight \
  --config /private/operator/native/controller-ops.json
```

Generation creates exclusive mode-0600 JSON files containing environment
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
fixtures may set `SSL_CERT_FILE=/run/operator/ca.crt`; no insecure production
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

Run worker commands on its Docker host, with the separate trusted operator ledger
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
An installed previous-version rollback and cross-host recovery remain acceptance
gates. The reopened Shanghai phase uses the dedicated Jenkins test task.
Remote Git publication remains paused; the historical Fleet publish task is not
used for this native deployment.

The Shanghai build-only Jenkins definition is versioned in
`examples/ecs-native/deploy/Jenkinsfile.shanghai-test`, with its public helper at
`scripts/ecs_native_build.py`. It reuses the dedicated test job and existing SSH
credential binding. Update the pinned archive/source hashes and owned build
identity together for a future release; never reuse an existing source directory
without validating every archive entry and rejecting extra files. The current
backend archive stays pinned independently from this CI supplement.

The builder uses its own Docker container, capped at one CPU and 2 GiB; selected
Docker HostConfig and kernel cgroup limits must pass before either image builds.
Backend and frontend builds run serially. The job verifies the shared NFS4 source
and marker on both peers, preserves SSH host-key checks, and stops only its owned
builder afterwards while retaining cache. It does not deploy services, modify
other Jenkins jobs, or print credentials, configuration environments or raw logs.
The first Shanghai installed run and cross-host browser/B/C evidence remain pending.

## Current Shanghai isolation and reboot mounts

The controller is `47.117.93.194` / `192.168.0.190`; the worker is
`47.117.149.57` / `192.168.0.189`. The previous worker public address is obsolete.
The build host is the existing Jenkins ECS `106.14.210.163`. The current public
backend archive is pinned to SHA256
`74c8502c341a7b32867d61f8ba6090f62cedb76e2045ab654113904bf05689d6`;
the CI supplement is separately versioned and does not change that archive.

Both peers have a verified NFS4 mount at `/srv/deerflow-data`, sourced from
`031sp6l7o6sh4hzha32-jow11.cn-shanghai.nas.aliyuncs.com:/`. This run created only
`/srv/deerflow-data/task6b-native-820d7a3429d9`, with matching marker
`pool/pool-mount-id`, and bound it to `/srv/deerflow-native-test` on both hosts.
Historical NAS directories are retained. After a host reboot, restore this bind
only after the original NFS mount and marker pass; do not create a local stand-in:

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

Run the operator preflight before starting either role. New project-scoped
PostgreSQL volumes will hold distinct native and executor databases; old volumes
and data are not reused. TLS for the owned test must contain the private controller
IP in its SAN and be verified using its owned CA; production TLS verification
remains mandatory. No insecure WSS flag is permitted. Installed startup, B/C
execution, native UI, cross-host WSS and prior-version rollback are not yet proved.

The bounded #8 registry failure occurs because an isolated BuildKit container
cannot consume the host engine's cached bases directly. The recovery helper uses
Docker 29's original OCI `image save` layout for the three immutable public base
pins, without format conversion. It verifies every exported blob hash and the
original index-to-Linux-amd64-manifest-to-config/layers chain, then uses the
[official OCI named build contexts](https://docs.docker.com/reference/cli/docker/buildx/build/#additional-build-contexts---build-context).
The dedicated builder's cgroup gate still applies. This changes neither backend
source/Dockerfile, dependency locks, TLS verification nor shared daemon settings.
Job #9 verified all three original base OCI chains but failed before APT because
the cached builder was BuildKit v0.9.3, whose builtin Dockerfile frontend lacks
named contexts. The recovery pins the owned builder to official stable
[BuildKit v0.33.1](https://github.com/moby/buildkit/releases/tag/v0.33.1), with
image index digest `sha256:cec9f139f45e93c5c69c60f8b07cfad9f43f4ef6b6a6cd917527fea5ff2e3dea`.
The original registry manifest SHA matches its response digest; the bounded host
pull succeeded. Only the stopped owned builder is migrated with `docker buildx rm
--keep-state`, preserving its state volume, then recreated under the same name and
resource limits. The helper rejects an existing builder with another image/version;
it does not reset unknown builders. Actual image identity, version and kernel
limits are recorded before building. Installed image acceptance remains pending.

The serial frontend stage applies the same OCI hash/descriptor verification to
the cached official Node image
`node@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402`,
using a `node:22-alpine` named context for the existing frontend Dockerfile.
Node OCI export and the current frontend build are pending actual stage execution;
no old Fleet frontend is substituted. This CI increment is separately hashed and
does not change the frozen backend archive.

The reviewed Chromium-stage Shanghai bundle has source SHA256
`25889ce34682442407ee3fa04c4f209bdeeb633f4ae1cc2d6323b3502d127855`.
It preserves all 3,798 original entries except the Dockerfile: HTTPS normalization
precedes `APT_MIRROR` substitution, and native-role copies only the builder
Debian sources file before Playwright installs Chromium system dependencies.
Both stages use the same fixed Python base. NodeSource configuration and
credentials are not copied; the existing default production target is unchanged. The CI supplies the
Debian-listed TUNA hostname; TLS and APT signatures/content hashes stay enabled.
A bounded Jenkins-host HTTPS probe downloaded 1 MiB in 0.926s; actual build-path
speed and installed acceptance remain unproved. Job #10 was normally stopped after the reviewed replacement inputs were ready;
its final result is `ABORTED` for a planned version switch, not a transport failure. The Chromium-stage inputs were prepared under `native-task6b-25889ce34682`
but were superseded by the diagnostic bundle below before being triggered.
The previous owned OCI directory and resource-capped builder/state are retained;
no base images or cache are pruned.

Job #11 passed all 3,798 fresh archive entries, 24 operator hashes, both NAS
checks, and actual BuildKit v0.33.1 CPU/memory gates. Its real APT layer used
HTTPS TUNA and reached compiler package unpacking at 21.23 seconds, compared
with 495 seconds for the previous index download alone. Remaining dependency
installation, final images and installed B/C/UI/WSS acceptance are pending.

Job #11 completed the APT/Node.js/Lark CLI layers and entered locked UV downloads
under `fe217c457dea`. Repeated download starts were traced to UV 0.11.1's
retry callback; current logs do not identify whether the transient cause is an
idle read timeout, reset, EOF or another retryable IO error. The timeout is an
idle read timeout, so wheel size alone does not establish its cause. Job #11 was
normally stopped after reviewed diagnostic inputs were ready; its final result
is `ABORTED` for a planned source/diagnostic switch, not a transport failure.

The diagnostic frozen source was
`305d6f933433c76c5cc4b3341d3041eb56d355e9906f535d282a64c3f1c338c6`,
archive SHA256 `ae3947eace7594a2b11110d7a6599127d6e9c5cfe0b8f929e8b91d4d4d539fac`.
It retains the HTTPS and Chromium-source fixes, adding optional build-only UV
logging. An unset argument preserves normal logging; only this CI supplies
`uv_client=trace,uv_distribution=debug`. Logs remain remote mode 0600 and are
not Jenkins artifacts; operator reports expose only allowlisted error classes,
counts and public package/registry hostnames. Fresh public inputs, `@tmp` and
verified two-target trust are ready under `native-task6b-305d6f933433`.
The same owned builder/state and verified OCI directory are retained. That build initially waited for an existing AssetForge release approval to
release the single executor. Its owner completed it; no other job was altered.
Build #12 subsequently ran the diagnostic source and was normally aborted for
the reviewed artifact mirror switch; no UV retry exception had been observed.

Build #13 used fixed HTTPS TUNA transport for wheel/sdist artifacts only. The
original registry, versions, dependencies, hashes and sizes were unchanged.
UV performed its existing locked hash verification, installed 230 packages and
completed in 163.0 seconds. The build trap restored the original lock bytes/SHA;
all seven visible owned-builder copies matched
`79c3181e1fcab20494d8cb07a8865e366354ef50a323c5b7a58dd59f20bfe217`.
Its subsequent official Chromium download remained active but slow: one sample
had 25,245,265 of 185,646,494 bytes, with 26,866 bytes/second over 124 seconds.
The estimated remaining 99.5 minutes applied only to that ZIP, not the complete
build. Official Microsoft alternate returned HTTP 400; direct official Google
storage did not establish a major sustained speed improvement in the bounded probe.

To verify the main path first, build #13 was normally aborted for an explicitly
interim core/UI version. Build #14 used source
`05e260329244d3194d23512320e88cf653206d7db75e34b737cf6e64b29401e8`,
archive SHA256 `15504f03420201e1058967f280daea86f7e738cee1ada4adfe2e218dad90daa1`.
The `native-core` stage retains the same installed environment, native schema
labels, entry point and application source. Its `-core` image proof explicitly
records `chromium_present=false`, `browser_installed=false` and capability
`pending_unavailable`; it must not be used for browser acceptance. The existing
`native-role` target still adds Chromium and system libraries, and the default
production target remains unchanged. Core was built once; subsequent controlled
Jenkins runs build only the current native UI and preserve that core origin. They
do not start a background browser build.
Reproduce the controlled build actions with `python3 scripts/ecs_native_build.py
backend-core` and `python3 scripts/ecs_native_build.py frontend` in the pinned
owned workspace. The full role remains the helper's separate `backend` action.
Deploy core using the generator's existing browser-unenabled configuration;
B/C/BC, image installation, native UI, cross-host WSS and complete-browser
acceptance remain pending actual execution. Build success is not system acceptance.


Builds #14–#16 were normally aborted after measured frontend memory reclaim
stagnation; they did not finish UI compilation. #16 used the reviewed Webpack
build worker and memory optimizations, but its 3 GiB builder reached its limit:
user CPU stopped at 289.9 seconds while system CPU and memory pressure grew.
No OOM kill or compile error was observed. Its post action stopped only the
owned Jenkins builder and preserved the cache.

The next controlled frontend build is #17, using the same immutable source
`56636cebddc6060cc4929a7f0fd86d45eb7c21c5890fb2f7f1d1128226ac4af5`
and archive SHA256
`e27c3d4ce58b7f762c09386cfe1fc97464c5df639dc2d855332713915e3fa34b`.
Jenkins coordinates an isolated controller builder with 1 CPU, 5 GiB memory and
zero swap. It requires at least 6.5 GiB available memory; controller roles remain
stopped during compilation. Only the verified Node OCI input is transported,
and the fixed official BuildKit digest is used. The core image is not rebuilt.
`scripts/ecs_native_controller_build.py` transports pinned public inputs and
returns the exact UI image archive and SHA proof to Jenkins;
`scripts/ecs_native_build.py` enables this fixed location only through
`ECS_NATIVE_CONTROLLER_BUILD=1`.

At the latest checkpoint, #17 was waiting for the single `shanghai-builder`
executor, occupied by `assetforge-shanghai-release #36` at its staging approval.
No other task was altered, and no duplicate build was queued. Controller input
transport/build and role deployment have not yet started. The reviewed host
bootstrap entry is `scripts/ecs_native_shanghai_deploy.py`; it starts only the
fixed owned namespace, keeps controller Docker access on the host and verifies
worker 500m/1 GiB limits. Its installed B/C and browser/WSS acceptance remain
pending. These mutable documentation updates do not rewrite any frozen archive.

The private configuration sequence is currently a reviewed proposal only; no
private role generation or startup is claimed. For later genuine C/BC acceptance,
reuse only the selected original DeepSeek model/provider fields and required env
references from `/Users/wenbinwang/Documents/git/deerflow2/config.yaml` and
`/Users/wenbinwang/Documents/git/deerflow2/.env`. Actual key values remain unread
in this phase; no whole historical config/env file is transferred. Task6 remains
unchecked, and final backend/blocking-I/O gates are pending.

After the owner handled release #36, #17 ran and failed before source extraction
or builder startup. All four fixed public inputs reached the controller with
root-owned mode 0600; source/builder/image proofs were absent. The fixed official
BuildKit host pull did not populate its cache. Docker daemon classification found
an HTTP `500 Internal` marker for the public registry; captured command output
was withheld, so no finer registry response cause is claimed. No compilation or
role startup occurred. The next reviewed recovery candidate reuses the already
cached official Jenkins BuildKit image as one additional fixed public archive,
with SHA verification and no-alias checks. Controller BuildKit uses its exact
image ID and separately records the official origin digest, avoiding a registry
pull after an unaliased image load. Source566 and core05 remain unchanged.

### Shanghai frontend checkpoint (#19)

Jenkins `deerflow-shanghai-test #19` completed `SUCCESS` with the reviewed controller-only frontend build. The owned BuildKit container stopped after the job; its actual budget remained 1 CPU / 5 GiB / no swap. The current-source UI image is `deerflow-native-ui:56636cebddc6`, ID `sha256:d302f8c890fbb3259f633fe38244d841f8614016cdf77818660d7bf949bb46de`, amd64, from source archive `e27c3d4ce58b7f762c09386cfe1fc97464c5df639dc2d855332713915e3fa34b`. Its by-ID archive is 526,795,264 bytes, SHA-256 `5b640b763117e93ad85c7c79e692fcb2afd20d772ef697e647f4d0cf1b1ae2f2`. The controller image/archive proofs were independently checked.

Build #20 uses the already-reviewed `PHASE=transfer` to move only the fixed core/UI/runtime artifacts. It is an installation preparation step; native owner initialization, cross-ECS B/C execution, browser completion, stop/restart/rollback acceptance, and final backend gates remain pending. This documentation update does not alter the immutable source archive.

Fixed transfer #20 completed `SUCCESS`: nine public artifacts were hash-verified and loaded only onto their required peers. Core `5dda…` is on both peers, UI `d302…` on the controller, PostgreSQL/Redis/Nginx on the controller, and Alpine on the worker. No role was started by transfer.

Bootstrap #21 refused before source extraction because the known owned deployment root was 0755 while the public-input helper required 0700; only that exact root on both peers was checked and tightened to 0700. The unchanged retry #22 verified the full source, started the fresh PostgreSQL/Redis/MCP/UI, and failed native Gateway readiness with `McpTaskConfigurationError`: native configuration rejects task toolsets when `mcp_tasks.enabled=false`. The correction under review confines the B zero-model fixture to disabled Gateway task notifications, empty Gateway toolsets/custom scope interceptor, and a separate owner-rebound read-only B snapshot retaining all original signed submit/status/cancel behavior. No native validator or executor authorization is relaxed. Owner/worker startup and B execution have not passed.

The B oneoff is infrastructure evidence through the accepted deterministic ToolNode and ordinary persistent MCP service, with a real API-created owner/thread and the actual outbound worker. It does not call a model or establish native C/BC Agent acceptance. Before genuine DeepSeek C/BC, delete the owned B thread through the native API, prove its pending notification rows are gone, and restore the original task toolsets/interceptor and `mcp_tasks.enabled=true` on both peers while retaining the real owner maps.


### Paused Shanghai checkpoint — 2026-10-10

#23 installed roles passed; the real B infrastructure main passed, while Jenkins #24 failed in its outer blank-line receipt parser. Native cleanup queue152 became #25 before the pause check; #25 ended FAILURE without cleanup proof, and no cleanup build remains active. Its continuation is recorded in the [persistent resume checkpoint](ecs-native-shanghai-resume-2026-10-10.md). Shared-node admission is drained with zero unreleased work, and the exact B job has no remaining worker container. No actual model key was read or paid call made; C/BC/browser/lifecycle/rollback/final gates remain pending. The user paused further work until tomorrow. No ECS shutdown, Compose stop, data deletion or other Jenkins task operation was performed.


## Resumed environment — 2026-10-10

The user restarted the two test ECS and authorized continuation. Current public addresses are controller `101.133.235.59` and worker `47.103.28.252`; their original host keys and unchanged private addresses `192.168.0.190` / `.189` were strictly verified. Historical public addresses above describe the earlier deployment. Jenkins transport uses the verified private addresses and its owned known-hosts file, so no transport target or TLS certificate change is required; TLS checks continue against the existing private SAN.

The main NAS mount survived, but the isolated bind did not. Both empty local bind targets were checked before restoring the exact verified NFS namespace to `/srv/deerflow-native-test`. Both now show nfs4, the original NAS endpoint and marker `820d7a3429d9`. Only existing owned Compose containers were started, controller first then worker; both starts waited successfully for health. No bootstrap, native DB login creation, image build or B rerun occurred. Root independently verified strict private-CA readiness. Admission remains drained.

A later retained receipt corrects the pause-time observation: `proof/b-main.json` already exists, root-owned 0600, timestamp `2026-10-09T17:06:29.051558Z`, SHA `a6fd2c864219cc89d18d831d7628078fe90409e9758049d2872150917cbe6cfd`. It was written by #25, not by today's recovery checks. #25's native DELETE returned HTTP 200 and removed the thread metadata, while the native terminal MCP task remained. The thread-delete API intentionally retains MCP task history; #25 failed its incorrect post-delete assertion that those rows must be zero. The task remains completed, ledger attempt1/physical stopped/cleanup_pending false, and thread metadata count is zero.

A narrow recovery candidate is under review: validate the complete retained B proof and the unique deleted-thread pending notification, keep admission drained, enable only the existing controller native MCP notification supervisor with the B-only empty task groups/interceptor configuration, and let the real Gateway callback reject the missing thread through the normal permanent-notification path. Acceptance requires dead_letter, zero pending notifications, zero native runs, and preserved terminal MCP/ledger history. This recovery has not yet executed; no actual model key or paid model call has been used. C/BC and remaining Task6 acceptance stay pending.


### Normal B notification recovery — Jenkins #26 SUCCESS

The reviewed recovery ran once through the existing Jenkins test job. The real Gateway notification service handled the already deleted B thread through its normal permanent-notification path. `proof/b-cleanup.json` records `notification_status=dead_letter`, zero pending notifications and zero native runs, one retained terminal MCP task, preserved execution ledger history, and no model calls. #26 ended SUCCESS; its queue is empty. No B task/thread was recreated and no SQL state patch was used. Admission remains drained while the original MCP configuration and selected DeepSeek model subset are prepared for genuine C/BC. C/BC/browser/lifecycle/rollback/final gates are not yet accepted.

### C main #27: native completion, tool delivery not accepted (2026-10-10)

The selected original DeepSeek model and only its referenced environment key were provisioned through the reviewed in-memory/SSH-stdin path. Both owned Gateway and worker resident were recreated to refresh their environment and became healthy before this single native API run. Jenkins #27 ended FAILURE because the delivery assertions failed: native run `e69ab8b5-7cf7-4181-89a6-02e5f66af011` reached `success`, and C ledger job `20d31d4d1f874b5e897ebcdab10f4dc3` completed at attempt 1 on `native-820d7a3429d9` with physical STOP recorded. Three bash attempts returned sandbox-capacity errors; no requested NAS output or read_file/present_files delivery was verified. This is not C acceptance PASS.

The installed AIO prefix `deer-native-820d7a3429d9` also selects Compose resident `deer-native-820d7a3429d9-worker-resident-1`. Native strict capacity counts this running role container as sandbox occupancy. The proposed repair separates AIO into `deer-native-aio-820d7a3429d9`, synchronizes operator prefixes, and rejects such overlap before future configuration generation. The worker resident later exited with code 0 and no OOM; the exact exit trigger remains unconfirmed. Admission remains drained. Existing run, thread, checkpoint and ledger history are retained; the repaired delivery main will use separate attempt receipts after review.

The historical bootstrap uses its original pinned generator. Changes to the public generator do not rewrite the installed immutable source archive; a future fresh deployment must create and review a new source bundle and matching CI pins. Full browser, BC, captured live sandbox cgroups, lifecycle/version rollback and final cloud gates remain pending.

### Repaired C delivery #29 (2026-10-10)

#28 failed before private writes or model invocation because the existing root-owned namespace parent was 0755 while the repair required 0700. Only that exact parent directory on each test host was tightened to 0700. The same reviewed package was then used once in #29; neither keys nor images were rebuilt or reread. Both peers now use AIO prefix `deer-native-aio-820d7a3429d9` and matching operator prefixes, with unchanged Compose projects.

The actual C delivery main passed: run `86a41bdc-a550-4557-81d9-1165e91ae8c7` completed through the native Gateway and remote worker `28512cfbcc7b:7766d0f431fa48e9a54e6719cae9dd32`. Native bash, read_file and present_files produced and delivered the shared NAS file with result `338350` and `Linux`. Ledger job `4e9c2ef12a0f49bda0c4a3b174582d18` completed at attempt 1 on the owned node, with physical STOP true and no pending cleanup. Controller proof `proof/c-repair-main.json` retains the prior #27 run identity rather than replacing its failed-delivery record. Finally-drain proof records operator_drain true and unreleased 0.

During this installation/run window, the new-prefix AIO container `8ba2dd136bf8b5b2402b375e49d737974ecd08d2f7ff76d235da2def8d8c49cf` was captured live. Docker NanoCpus was 1000000000 and Memory was 1073741824; kernel cpu.max was `100000 100000` and memory.max was `1073741824`. The root reviewer independently verified these selected limits. Worker proof `proof/c-repair-live-aio.json` records the observation; it does not claim a separately established run-to-container binding. BC, live B-container limits, full browser/WSS, lifecycle/version rollback and final cloud gates remain pending.

## Publication derivative checkpoint — 2026-10-10

Jenkins #31 failed before builder start because Docker 29's manifest image identity was incorrectly compared with the OCI config digest. The reviewed identity fix preserves all archive/blob/hash checks. #32 SUCCESS built only `publication.py` over exact core manifest `5dda8660e81a531beb2b36ec0ab556f03df71ff8cbfc0e69abeb1d72643dd338`, original archive `4bddb0efba126620ac03c6329e8858b10af7a72d01f28dd7293563fbf1cd3cdf`. The immutable derivative is `sha256:a216a2cc51b248687b296120b23a2b382cda89a72dfaf27e5eae54cf027397a1`, publication patch `bdd2931a1a6f8f35b9eb191fb809aa38c8dae85b6e65b44c15feb3d8a6cc8a9e`. It retains the original locked dependencies and has no Chromium.

Two owned, network-disabled cloud regressions passed, one case each: real non-root native publication reading and the sandbox/role namespace collision guard. They invoked no models. The exact owned builder stayed at 1 CPU / 3 GiB / zero swap and is stopped after the build. #33 SUCCESS transferred the fixed derivative to both private targets without starting roles or resuming admission. Public proofs are in the Jenkins owned workspace `proof/publication-{builder,image,green,transfer}.json`. Installed roles remain on the original core until the separately reviewed refresh runs; #30's failed continuation/goal/task audit remains intact.

The three-file Ruff check found import ordering, one long test command, and formatting changes. These remain pending source cleanup after the BC main; no formatter candidate has been applied and no claim of formatting PASS is made. The original immutable source566 archive is unchanged. Task6, browser, lifecycle/rollback, final gates and a coherent new cold-start source bundle remain open.


## Installed main acceptance checkpoint — 2026-10-10 (#34–#36)

#34 SUCCESS refreshed only the owned Gateway, MCP service and worker resident to immutable publication derivative `sha256:a216a2cc51b248687b296120b23a2b382cda89a72dfaf27e5eae54cf027397a1`. Its base remains core `5dda8660e81a531beb2b36ec0ab556f03df71ff8cbfc0e69abeb1d72643dd338`, with publication patch `bdd2931a1a6f8f35b9eb191fb809aa38c8dae85b6e65b44c15feb3d8a6cc8a9e`; this is a derivative identity, not a rewritten source566 image. Controller Gateway is healthy without a Docker socket; MCP runs without a healthcheck or socket. Worker resident is healthy with the approved socket, Docker 500m / 1 GiB and matching kernel limits. Strict private-CA readiness passed.

The single repaired native goal C → B → C trial actually passed in #35: thread `native-bc-repair-820d7a3429d9-06c502b422e54e648ba3a4216b0c1fde`, source run `70af1fb0-1d51-4b5f-81fb-4de17bfc47cf`, continuation run `5c4933af-2d51-404a-b2a3-affadf7dd93c`, B job `28aa3063aaf4490f881e2b039efdb752`. Both native Runs succeeded and all three ledger jobs completed physically on node `native-820d7a3429d9`; B used attempt 1 and started after source C physical STOP. Original goal identity and continuation budget, automatic notification, native ecs_submit/read_file/present_files, shared NAS `dependency-proof-338350`, authenticated artifact HTTP 200 and final goal clearing were independently verified.

Jenkins #35 remains FAILURE: its wrapper incorrectly expected terminal `notification_run_id` to retain the continuation ID. Native `finish_notification_run` deliberately clears this dispatch lease on delivered notification. #36 SUCCESS ran only a read-only verifier over that same trial; it invoked no model and created no run/goal. It verified persistent `dependency_wait.continuation_run_id` plus native run idempotency key `mcp-dependencies:<source_run_id>`, delivered status with equal event/notified versions and a cleared lease. Controller root-owned 0600 `proof/bc-repair-main.json` SHA is `1998bdb6079bc28c9c7681904093a5744d0a025fa769b36da18394775b01236c`; Jenkins retains `proof/bc-repair-verification.json`. Prior #30 failed history is preserved.

The root reviewer captured the actual B container `590d3e5813791ddb0647db677eeb28cc42896a0f04ba456c7807879580c39ce5` and independently bound it to this trial: 500m CPU, 128 MiB memory, PID limit 64, network none, user `65534:65534`, with matching kernel cgroups. No extra B trial was run for this observation. Final admission remains drained, unreleased jobs/nonterminal native runs/pending notifications are zero, and the owned roles remain healthy/running as described above.

B infrastructure, genuine C delivery and genuine native BC main are now accepted for this installed two-ECS/NAS scope. At this #36 checkpoint, full Chromium/browser/cross-host WSS, lifecycle/version rollback, final backend/blocking-I/O gates, Ruff source cleanup and a coherent new cold-start source bundle/pins remained pending; see the subsequent lifecycle/static-cleanup checkpoint below. Task6 is still unchecked; no Git commit/push or additional model/build/test phase was performed for this final verification. The immutable source566 archive remains unchanged.


## Installed lifecycle and static source cleanup — 2026-10-10 (#37–#38)

#37 failed before its first snapshot or any service mutation: the lifecycle preflight incorrectly expected the controller operator's Compose path under `ROOT/source`, while its original generated path is `ROOT/frontend-build/source`. The narrow correction accepts only that exact historical controller path, rejects symlinks through every ancestor, and verifies both public Compose files have identical bytes. The worker path remains unchanged. Private operator configuration was not rewritten; the original failed helper and #37 result remain retained. Both corrected read-only host snapshots passed before the one #38 execution.

#38 SUCCESS verified this fixed installed sequence on image `sha256:a216a2cc51b248687b296120b23a2b382cda89a72dfaf27e5eae54cf027397a1`: worker installed `ecs_executor.operations stop`; controller host Compose stop of Gateway/MCP/frontend/proxy; controller host Compose start of those services; worker installed `start`; worker installed `restart`. Controller PostgreSQL and Redis remained running. Worker commands ran in the bounded trusted oneoff with its separately fenced operator environment; no ledger/admin credentials were added to the resident. Controller native CLI lifecycle was not tested because the host has no installed Python environment; no controller socket container was introduced.

All nine snapshots/action steps passed. Fresh drain/idle/physical-work, real NFS namespace and strict private-CA readiness gates passed. Container IDs and persistent volume identities, complete terminal runs/MCP/ledger row hashes, prior B/C/BC proof hashes and the BC NAS output hash remained identical. Gateway and worker are healthy, MCP runs without a healthcheck, the worker remains 500m / 1 GiB, and admission remains drained. No model, thread, image selection, rollback, key/config change, OS shutdown, volume deletion or prune occurred. Jenkins root/agent-owned 0600 `proof/installed-lifecycle.json` SHA is `d4195da7183a32bbf09b320133f649c428e7b2601158ca93b2529c6dfce96dae`, independently verified by the root reviewer.

To reproduce this installed slice, use the existing Jenkins `deerflow-shanghai-test` normal `shanghai-deploy-ssh` binding with `PHASE=installed-lifecycle` and the unchanged source archive SHA `e27c3d4ce58b7f762c09386cfe1fc97464c5df639dc2d855332713915e3fa34b`. The reviewed coordinator is `scripts/ecs_native_shanghai_lifecycle_transport.py`; it pins `scripts/ecs_native_shanghai_lifecycle_host.py`, uses only the two fixed private hosts, and refuses an existing/partial lifecycle receipt rather than overwriting history or blindly rerunning. A subsequent trial requires a separately reviewed fresh receipt identity.

The future BC admitting script now verifies delivered notification versions and a cleared dispatch lease, using fresh source `dependency_wait.continuation_run_id` plus native run idempotency for durable linkage. This source correction does not rewrite the already installed/frozen #35 script pins and did not rerun the accepted model trial. Static Ruff check and format checks passed for that script, publication.py and its two focused tests (four files); the publication cleanup was import/format only. Current runtime image still contains reviewed publication patch `bdd293…`; the newly formatted public publication source is `0fd2f696…`. A coherent new cold-start source/image/CI bundle remains pending.

Remaining scope: full browser/Chromium and cross-host WSS, immutable version rollback, OS/reboot recovery acceptance, final backend/blocking-I/O gates, and coherent cold-start bundle/pins. The worker CLI/controller host Compose lifecycle slice is accepted; it is not a full controller CLI or rollback acceptance. Task6 remains unchecked.


## Shanghai browser image checkpoint (2026-10-10)

Current owned Gateway/MCP/resident image is `sha256:52ce23272ed5c945389367eb92f97fdd6754aa93d1c369bb01d7a44d45c5f47e`, a browser derivative of publication imagea216. It uses locked Playwright1.61.0, Chromium headless-shell149.0.7827.55 and FFmpeg from the verified official MCR layer, with Debian dependencies installed by Playwright. No other browsers or model keys are embedded. #44 enabled the native browser provider and original eight browser tools; worker physical limits remain500m/1GiB, while logical resident capacity includes the warm AIO reservation.

Only owned application roles were refreshed; PG/Redis/frontend/proxy, history and NAS output hashes stayed unchanged. Private browser-change backups remain on each original host as `*.before-browser-control`, root-owned0600. Namespace/resident directories remain0700; the established outer `ROOT/private` directory may be root-owned0755 provided it is not group/world writable. #46 accepted strict native HTTP/WSS control and normal cleanup. Exact receipts and failed-build corrections are recorded in the resume document. Compatible version rollback and OS recovery are separate acceptance scopes; the current manual NAS bind restoration and explicit role startup must not be described as automatic boot recovery.

The nine successful public browser helpers are now retained under `scripts/ecs_native_browser_*`, with exact reviewed SHA pins preserved and eight Python files passing Ruff lint/format checks. Current cloud Jenkins pipeline still retains historical failed-build phases for audit; it must not be copied as a fresh cold-start pipeline without reconciling its helper inventory and pins. #46 post-cleanup returned404 after the main's normal DELETE200; peers remain healthy on52ce, admission drained and owned AIO idle.


## Same-schema version rollback and restoration — #47–#48

#47 failed before its first private preparation write because the executor revision query used the native database table name. The repaired query uses `ecs_executor_alembic_version`; native revision checks continue to use `alembic_version`. A submission-only worker check then exposed host `ps` incompatibility in `docker top`. The repaired guard reads only executable basenames in the verified owned resident, ignores normal process exit races and refuses unexpected read errors. Both final host preparations passed a denied-write diagnostic through their first lock creation before the single #48 retry. Failed scripts/build evidence remain retained.

#48 main PASS verified browser image52ce → compatible publication image a216 → image52ce with both restoration generations prepared before any service stop. Worker selection uses the installed `ecs_executor.operations select-version`; controller selection uses the guarded host operator while PostgreSQL/Redis stay running. This does not claim the controller native CLI selector or a database time rollback was tested. All 20 preparation/action/snapshot steps passed, and root independently verified `proof/compatible-rollback.json` SHA `90448af01e4a20337451407832c2b793225abb143b2a9c392035be14e5ffda03`.

Both roles returned healthy on the original browser image. Original configuration fingerprints, unrelated private-file hashes, full terminal Run/MCP/ledger history hashes, NAS output hashes, persistent volumes and PostgreSQL/Redis/frontend/proxy container records were preserved. Resource limits remain unchanged; admission remains drained, no model calls or new jobs were made. Jenkins #48 finished SUCCESS with independent post `ALREADY_RESTORED_VERIFIED`; post did not stop the restored roles again. OS reboot, automatic NAS remount and final frozen-source backend gates are not accepted by this slice. Final gates and coherent artifact documentation remain pending.


## Frozen-source backend gate — #49 FAILURE (fixture-only repair pending)

The immutable public source snapshot is `779e52ecb2027efd817e90cd9b591b95404afbb7df70f039abd575bf5ef6f320`; archive `deer-native-final-source-779e52ecb202.tar.gz` SHA `139ec6eb73f863884156c6f0c2261e781ba7e2c7c98362ad95a2f793ac3f6ae6` (30,353,723 bytes); embedded entry-manifest SHA `8bb32682ea303b67d1c95b680dc00d1af96e98e3643374d23ca7f70c8b0082e9`. Root verified 3,852 regular entries and preserved the original source566 archive. Upload to Jenkins was hash-verified, UID999/mode0600; `proof/final-source-upload.json` SHA `dd51a0acfbfbbfa82670314d90a029d7fb838044d007b616a487ca5011a15100`.

#49 finished FAILURE using this snapshot in a fresh network-none, root UID, 1 CPU / 3 GiB fixture with only the read-only public archive mount. No credentials, database, NAS or Docker socket were mounted. All four application packages resolved to the freshly verified temporary source. Ruff check and format passed; all four default suite shards exited 2 at collection because the static-detector root resolver requires a `.git` marker. The public package correctly excludes real Git metadata. Blocking-I/O completed with 229 passed and two warnings. This does not count the default backend suite as passed.

The fixture automatically exited and was removed. Independent exact-CID inspection returned the canonical no-such-container error and one LF on stdout (`b'\n'`). The overly strict cleanup wrapper expected zero stdout bytes, so main and post refused before writing an overall gate receipt. No `fixture_cleanup=true` receipt exists; the independent absence observation is the narrower evidence. Original active marker, source archive, logs and failed build are retained. Public log SHA: `3d00c2877b1d0394f97502c6c8824fa1589581a43c03adb68d4ae20ce5877a01`.

The next fixture-only repair generates an empty `.git` marker after complete source verification and accepts only the two verified missing-container stdout shapes, empty or one LF, alongside exact return-code/canonical full-ID stderr checks. No runtime code, private configuration, tests or accepted B/C/browser/rollback mains are changed. The repair uses fresh artifact/active-marker identities, preserving #49. New frozen-source gates have not yet run.
