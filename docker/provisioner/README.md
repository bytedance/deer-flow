# DeerFlow Sandbox Provisioner

The **Sandbox Provisioner** is a FastAPI service that dynamically manages sandbox Pods in Kubernetes. It provides a REST API for the DeerFlow backend to create, monitor, and destroy isolated sandbox environments for code execution.

## Architecture

```
┌────────────┐  HTTP  ┌─────────────┐  K8s API  ┌──────────────┐
│  Backend   │ ─────▸ │ Provisioner │ ────────▸ │  Host K8s    │
│  (gateway/ │        │   :8002     │           │  API Server  │
│ langgraph) │        └─────────────┘           └──────┬───────┘
└────────────┘                                          │ creates
                                                        │
                          ┌─────────────┐         ┌────▼─────┐
                          │   Backend   │ ──────▸ │  Sandbox │
                          │ (NodePort   │ or DNS  │  Pod(s)  │
                          │  /ClusterIP)│         └──────────┘
                          └─────────────┘
```

### How It Works

1. **Backend Request**: When the backend needs to execute code, it sends a `POST /api/sandboxes` request with a `sandbox_id`, `thread_id`, optional `user_id`, and the configured `skills_container_path` (default: `/mnt/skills`).

2. **Pod Creation**: The provisioner creates a dedicated Pod in the `deer-flow` namespace with:
   - The sandbox container image (all-in-one-sandbox)
   - HostPath volumes mounted for:
     - `{skills_container_path}/{public,custom,legacy}` → Default read-only skill projections
     - `{skills_container_path}/integrations` → Optional read-only managed-integration projection supplied by the Gateway
     - `/mnt/user-data` → Read-write access to thread-specific data
   - Resource limits (CPU, memory, ephemeral storage)
   - Readiness/liveness probes

3. **Service Creation**: A Service is created to expose the Pod. By default this is a NodePort Service for Docker Compose compatibility. Set `SANDBOX_SERVICE_TYPE=ClusterIP` when the backend runs inside the Kubernetes cluster.

4. **Access URL**: In NodePort mode, the provisioner returns `http://{NODE_HOST}:{NodePort}`. In ClusterIP mode, it returns a Kubernetes service DNS URL like `http://sandbox-{sandbox_id}-svc.{namespace}.svc.cluster.local:8080`.

5. **Cleanup**: When the session ends, `DELETE /api/sandboxes/{sandbox_id}` removes both the Pod and Service.

The sandbox business endpoints are implemented as synchronous FastAPI handlers
because the Kubernetes Python client used here is synchronous. Starlette runs
sync handlers in its worker pool, keeping create/read/list/delete K8s API calls
and service access polling off the ASGI event-loop thread. Keep `/health`
lightweight; do not move the sandbox CRUD handlers back to `async def` unless
the K8s client path is also made async or explicitly offloaded.

## Requirements

Host machine with a running Kubernetes cluster (Docker Desktop K8s, OrbStack, minikube, kind, etc.)

### Enable Kubernetes in Docker Desktop
1. Open Docker Desktop settings
2. Go to "Kubernetes" tab
3. Check "Enable Kubernetes"
4. Click "Apply & Restart"

### Enable Kubernetes in OrbStack
1. Open OrbStack settings
2. Go to "Kubernetes" tab
3. Check "Enable Kubernetes"

## API Endpoints

### `GET /health`
Health check endpoint.

**Response**:
```json
{
  "status": "ok"
}
```

### `POST /api/sandboxes`
Create a new sandbox Pod + Service.

**Request**:
```json
{
  "sandbox_id": "abc-123",
  "thread_id": "thread-456",
  "user_id": "user-789"
}
```

`user_id` is optional for backwards compatibility and defaults to `default`. When `USERDATA_PVC_NAME` is set, the provisioner uses it to isolate PVC-backed user-data directories.

When the Gateway mounts that same storage at its DeerFlow home and the PVC
subpaths align, set `sandbox.thread_data_mounts: true` in the Gateway's
`config.yaml` to skip redundant upload-time sandbox acquire/sync. Leave the
field unset when using unrelated storage or when the mount relationship is
uncertain.

**Response**:
```json
{
  "sandbox_id": "abc-123",
  "sandbox_url": "http://host.docker.internal:32123",
  "status": "Pending"
}
```

**Idempotent**: Calling with the same `sandbox_id` returns the existing sandbox info.

### `GET /api/sandboxes/{sandbox_id}`
Get status and URL of a specific sandbox.

**Response**:
```json
{
  "sandbox_id": "abc-123",
  "sandbox_url": "http://host.docker.internal:32123",
  "status": "Running"
}
```

**Status Values**: `Pending`, `Running`, `Succeeded`, `Failed`, `Unknown`, `NotFound`

### `DELETE /api/sandboxes/{sandbox_id}`
Destroy a sandbox Pod + Service.

**Response**:
```json
{
  "ok": true,
  "sandbox_id": "abc-123"
}
```

### `GET /api/sandboxes`
List all sandboxes currently managed.

**Response**:
```json
{
  "sandboxes": [
    {
      "sandbox_id": "abc-123",
      "sandbox_url": "http://host.docker.internal:32123",
      "status": "Running"
    }
  ],
  "count": 1
}
```

## Configuration

The provisioner is configured via environment variables (set in [docker-compose-dev.yaml](../docker-compose-dev.yaml)):

| Variable | Default | Description |
|----------|---------|-------------|
| `K8S_NAMESPACE` | `deer-flow` | Kubernetes namespace for sandbox resources |
| `SANDBOX_IMAGE` | `enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest` | AIO-compatible container image for sandbox Pods |
| `LARK_CLI_INIT_IMAGE` | empty (feature off) | Optional lark-cli init image (Pattern A). When set, sandbox Pods requesting the lark-cli runtime get an init container + shared `emptyDir` that provisions `lark-cli`, instead of a hostPath/PVC runtime mount. See [`docker/lark-cli-init`](../lark-cli-init/README.md) |
| `LARK_CLI_BROKER_IMAGE` | empty (feature off) | Optional lark-cli broker image (Pattern B, issue #4338). When set, sandbox Pods requesting the broker get a shim init container + a `lark-cli-broker` sidecar that holds the credentials; the plaintext `config`/`data` are mounted into the **sidecar only**, never the sandbox. Supersedes `LARK_CLI_INIT_IMAGE` when both are set. See [`docker/lark-cli-broker`](../lark-cli-broker/README.md) |
| `THREADS_HOST_PATH` | - | **Host machine** path to threads data directory (must be absolute) |
| `DEER_FLOW_HOST_BASE_DIR` | `/.deer-flow` | **Host machine** DeerFlow data root containing global and per-user `skills_view` projections |
| `SKILLS_PVC_NAME` | empty (use hostPath) | PVC name for the operator-managed skills root used by unrestricted threads. The Gateway does not populate this PVC; see [PVC skills setup](#pvc-skills-setup) |
| `SKILLS_PVC_SUBPATH_TEMPLATE` | empty | Optional `subPath` template for `SKILLS_PVC_NAME`. Supports `{user_id}` and `{thread_id}`. When empty, the skills PVC root is mounted unchanged |
| `USERDATA_PVC_NAME` | empty (use hostPath) | PVC name for user-data volume; when set, uses PVC with `subPath: deer-flow/users/{user_id}/threads/{thread_id}/user-data` |
| `KUBECONFIG_PATH` | `/root/.kube/config` | Path to kubeconfig **inside** the provisioner container |
| `SANDBOX_SERVICE_TYPE` | `NodePort` | Service type for sandbox access. Use `ClusterIP` when backend and provisioner run inside the same Kubernetes cluster |
| `NODE_HOST` | `host.docker.internal` | Hostname that backend containers use to reach host NodePorts; ignored when `SANDBOX_SERVICE_TYPE=ClusterIP` |
| `K8S_API_SERVER` | (from kubeconfig) | Override K8s API server URL (e.g., `https://host.docker.internal:26443`) |

For new sandbox requests, the Gateway also sends the effective AIO shell-session
capacity derived from `subagent_runtime.max_running`. The provisioner writes it
to the sandbox Pod as `MAX_SHELL_SESSIONS`; requests from older Gateways omit the
field and retain the image default. Discovery responses report the effective
capacity. The Gateway replaces a lower-capacity Pod through its ownership-fenced
replacement path once the previous owner and recovery grace permit it. A create
request for an existing Pod with insufficient capacity returns HTTP 409; the
provisioner does not delete an existing Pod to upgrade its capacity, including
after a transient Gateway discovery failure. If the old Pod has already gone
but its Service remains, create can safely provision the missing Pod.

### Custom sandbox image

Provisioner-created sandbox Pods use the provisioner's `SANDBOX_IMAGE` environment variable. This is separate from `sandbox.image` in `config.yaml`, which applies to local Docker or Apple Container mode.

For persistent dependencies, build an image that extends the default `all-in-one-sandbox` image and set `SANDBOX_IMAGE` to your published tag. A from-scratch image must remain compatible with the AIO sandbox HTTP API consumed by `agent-sandbox`, keep `/mnt/user-data` writable, and listen on the configured sandbox port.

See [Building a Custom AIO Sandbox Image](../../backend/docs/CONFIGURATION.md#building-a-custom-aio-sandbox-image) for the runtime contract and a minimal Dockerfile example.

### Lark CLI sandbox runtime (Pattern A)

Agents run `lark-cli` **inside** the sandbox, so the binary must exist in the
sandbox container. Instead of the Gateway downloading Linux binaries from GitHub
at install time and mounting them via hostPath/PVC, the provisioner can inject
`lark-cli` with an **init container + shared `emptyDir`**:

1. Publish a lark-cli init image (see [`docker/lark-cli-init`](../lark-cli-init/README.md))
   and set `LARK_CLI_INIT_IMAGE` on the provisioner.
2. When a sandbox is created with `provision_lark_cli_runtime: true` (the Gateway
   sends this automatically once the managed Lark skill pack is installed), the
   Pod gets a `lark-cli-runtime` `emptyDir`, an `lark-cli-init` init container
   that copies the runtime into it, and a read-only runtime mount on the sandbox
   container at `/mnt/integrations/lark-cli/runtime`. Any hostPath/PVC extra
   mount at that path is dropped (the init container supersedes it); the per-user
   `config`/`data` credential mounts are unchanged.

`GET /api/capabilities` returns `{"lark_cli_init_image": true|false}` so the
Gateway can surface a sandbox-runtime readiness signal in
`/api/integrations/lark/status` — a green UI can't then hide a chat-time
`lark-cli: command not found`.


### PVC User-Data Upgrade Note

Older provisioner versions mounted PVC user-data from `threads/{thread_id}/user-data`. The user-scoped layout mounts from `deer-flow/users/{user_id}/threads/{thread_id}/user-data`.

If an existing deployment already has PVC-backed user-data under the legacy layout, migrate the DeerFlow data directory before relying on the new PVC subPath. Mount the same PVC path that the gateway uses as its DeerFlow base directory, then run the existing user-isolation migration script:

```bash
cd backend
PYTHONPATH=. python scripts/migrate_user_isolation.py --dry-run
PYTHONPATH=. python scripts/migrate_user_isolation.py --user-id <target-user-id>
```

This moves legacy `threads/{thread_id}/user-data` data under `users/<owner>/threads/{thread_id}/user-data`, which matches the new provisioner PVC subPath when the gateway base directory is mounted at `deer-flow/` on the PVC. `<owner>` is the thread's `user_id` in the `threads_meta` table of the gateway's configured database (`default` when none is recorded), so run the script with the gateway's `config.yaml` and database settings; if that table cannot be read, it stops without moving anything. Pass `--allow-missing-thread-owners` only when the install never recorded thread owners. `--user-id` picks who inherits un-owned global data (memory, `USER.md`, legacy custom agents). Run the migration while no gateway or sandbox Pods are writing to those paths.

Before this fix, the script never found the database and moved every legacy thread to `users/default/threads/`. Re-running it does nothing then, because `threads/` is gone. To recover, stop the gateway and list the threads with a real owner:

```sql
SELECT thread_id, user_id FROM threads_meta WHERE user_id IS NOT NULL AND user_id <> 'default';
```

Move each listed `users/default/threads/{thread_id}` that exists back to `threads/{thread_id}`, then run the script again (dry run first). Threads whose owner is `default` or not recorded stay where they are. If an owner has used the thread since, `users/<owner>/threads/{thread_id}` already exists; the script never overwrites it and sets the old copy aside in `migration-conflicts/{thread_id}` for you to merge by hand.

### PVC Skills Setup

Choose the skills mount mode before deploying. Setting `SKILLS_PVC_NAME` alone does not make per-user custom or legacy skills available in sandbox Pods.

| Thread configuration | Skills source inside the sandbox | Who populates it? |
| --- | --- | --- |
| Custom lead Agent with an explicit `skills` list and shared `USERDATA_PVC_NAME` | Four category subpaths on the user-data PVC | Gateway, before sandbox acquire |
| New unrestricted thread with `SKILLS_PVC_NAME` | Skills PVC root, or `SKILLS_PVC_SUBPATH_TEMPLATE` within it | Operator |
| hostPath mode | Enabled-only projections under `DEER_FLOW_HOST_BASE_DIR` | Gateway, before sandbox acquire |

**Gateway-managed skills on a shared PVC.** Configure a custom lead Agent with an explicit `skills` list containing the required skill names. An omitted or `null` list is unrestricted; `[]` disables all skills. The Gateway materializes the selected, user-visible skills under `users/{user_id}/threads/{thread_id}/skills_view/{public,custom,legacy,integrations}` in its DeerFlow home. Mount the same storage into the Gateway and set `USERDATA_PVC_NAME` for the provisioner, aligning the Gateway home with `deer-flow/` on that PVC. Sandbox Pods then mount the four categories from `deer-flow/users/{user_id}/threads/{thread_id}/skills_view/{category}`. All four category overrides replace the default skills mount, including `SKILLS_PVC_NAME` if set. The PVC must support access from the Gateway and the nodes running sandbox Pods; setting its name only on the provisioner does not share the Gateway's files.

**Operator-managed skills PVC for unrestricted threads.** New threads using the default lead Agent or custom Agents with omitted or `null` `skills` use the flat skills-PVC mount. With `SKILLS_PVC_NAME` set, the provisioner mounts the PVC root at `skills.container_path` (default `/mnt/skills`), or the subdirectory selected by `SKILLS_PVC_SUBPATH_TEMPLATE`. Populate that mount source with the category directories `public/`, `custom/`, `legacy/`, and `integrations/` required by the skills you expose. A directory named `custom/` in an old global skills tree does not supply the expected `legacy/` path. The Gateway does not copy per-user skills into this mount or refresh it after skill changes; the operator must maintain the contents and any user-specific layout. The provisioner logs a fallback warning for this mode. A thread that already has a policy-scoped projection keeps that mount root when its policy becomes unrestricted; the Gateway rebuilds that projection with all enabled, user-visible skills. Automatic materialization for new unrestricted PVC-backed threads remains tracked in [#4030](https://github.com/bytedance/deer-flow/issues/4030).

In hostPath mode, the Gateway materializes enabled-only views under `skills_view/public` and `users/{user_id}/skills_view/{custom,legacy}` beneath `DEER_FLOW_HOST_BASE_DIR`; the provisioner mounts those stable directories. Explicit lead Agent policies instead supply the four thread category mounts described above.

**hostPath skills volumes require the gateway and the K8s node to see the same `DEER_FLOW_HOST_BASE_DIR`** (single-node deployment, or NFS/shared storage mounted at that path on every node). The gateway writes the projection there before every sandbox acquire, so as long as that path is shared, the directory the provisioner mounts always exists by the time the Pod is scheduled — even a boot-time rebuild failure for one user self-heals on their next acquire, before the provisioner is called. `skills-custom` and `skills-legacy` use hostPath type `Directory` (not `DirectoryOrCreate`): if the shared-storage assumption is violated — the gateway wrote to a different node than the one the Pod lands on — Pod creation now fails visibly instead of silently mounting an empty directory. For multi-node clusters, choose a PVC setup above with the required access mode and contents.

### Important: K8S_API_SERVER Override

If your kubeconfig uses `localhost`, `127.0.0.1`, or `0.0.0.0` as the API server address (common with OrbStack, minikube, kind), the provisioner **cannot** reach it from inside the Docker container. 

**Solution**: Set `K8S_API_SERVER` to use `host.docker.internal`:

```yaml
# docker-compose-dev.yaml
provisioner:
  environment:
    - K8S_API_SERVER=https://host.docker.internal:26443  # Replace 26443 with your API port
```

Check your kubeconfig API server:
```bash
kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}'
```

## Prerequisites

### Host Machine Requirements

1. **Kubernetes Cluster**: 
   - Docker Desktop with Kubernetes enabled, or
   - OrbStack (built-in K8s), or
   - minikube, kind, k3s, etc.

2. **kubectl Configured**:
   - `~/.kube/config` must exist and be valid
   - Current context should point to your local cluster

3. **Kubernetes Access**:
   - The provisioner needs permissions to:
     - Create/read/delete Pods in the `deer-flow` namespace
     - Create/read/delete Services in the `deer-flow` namespace
     - Read Namespaces (to create `deer-flow` if missing)

4. **Host Paths**:
   - `DEER_FLOW_HOST_BASE_DIR` and `THREADS_HOST_PATH` must be **absolute paths on the host machine**
   - These paths are mounted into sandbox Pods via K8s HostPath volumes
   - The paths must exist and be readable by the K8s node

### Docker Compose Setup

The provisioner runs as part of the docker-compose-dev stack:

```bash
# Start Docker services (provisioner starts only when config.yaml enables provisioner mode)
make docker-start

# Or start just the provisioner
docker compose -p deer-flow-dev -f docker/docker-compose-dev.yaml up -d provisioner
```

The compose file:
- Mounts your host's `~/.kube/config` into the container
- Adds `extra_hosts` entry for `host.docker.internal` (required on Linux)
- Configures environment variables for K8s access

## Testing

### Manual API Testing

```bash
# Health check
curl http://localhost:8002/health

# Create a sandbox (via provisioner container for internal DNS)
docker exec deer-flow-provisioner curl -X POST http://localhost:8002/api/sandboxes \
  -H "Content-Type: application/json" \
  -d '{"sandbox_id":"test-001","thread_id":"thread-001","user_id":"user-001"}'

# Check sandbox status
docker exec deer-flow-provisioner curl http://localhost:8002/api/sandboxes/test-001

# List all sandboxes
docker exec deer-flow-provisioner curl http://localhost:8002/api/sandboxes

# Verify Pod and Service in K8s
kubectl get pod,svc -n deer-flow -l sandbox-id=test-001

# Delete sandbox
docker exec deer-flow-provisioner curl -X DELETE http://localhost:8002/api/sandboxes/test-001
```

### Verify from Backend Containers

Once a sandbox is created, the backend containers (gateway, langgraph) can access it:

```bash
# Get sandbox URL from provisioner
SANDBOX_URL=$(docker exec deer-flow-provisioner curl -s http://localhost:8002/api/sandboxes/test-001 | jq -r .sandbox_url)

# Test from gateway container
docker exec deer-flow-gateway curl -s $SANDBOX_URL/v1/sandbox
```

## Troubleshooting

### Issue: "Kubeconfig not found"

**Cause**: The kubeconfig file doesn't exist at the mounted path.

**Solution**: 
- Ensure `~/.kube/config` exists on your host machine
- Run `kubectl config view` to verify
- Check the volume mount in docker-compose-dev.yaml

### Issue: "Kubeconfig path is a directory"

**Cause**: The mounted `KUBECONFIG_PATH` points to a directory instead of a file.

**Solution**:
- Ensure the compose mount source is a file (e.g., `~/.kube/config`) not a directory
- Verify inside container:
  ```bash
  docker exec deer-flow-provisioner ls -ld /root/.kube/config
  ```
- Expected output should indicate a regular file (`-`), not a directory (`d`)

### Issue: "Connection refused" to K8s API

**Cause**: The provisioner can't reach the K8s API server.

**Solution**:
1. Check your kubeconfig server address:
   ```bash
   kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}'
   ```
2. If it's `localhost` or `127.0.0.1`, set `K8S_API_SERVER`:
   ```yaml
   environment:
     - K8S_API_SERVER=https://host.docker.internal:PORT
   ```

### Issue: "Unprocessable Entity" when creating Pod

**Cause**: HostPath volumes contain invalid paths (e.g., relative paths with `..`).

**Solution**: 
- Use absolute paths for `DEER_FLOW_HOST_BASE_DIR` and `THREADS_HOST_PATH`
- Verify the paths exist on your host machine:
  ```bash
  ls -la /path/to/skills
  ls -la /path/to/backend/.deer-flow/threads
  ```

### Issue: Pod stuck in "ContainerCreating"

**Cause**: Usually pulling the sandbox image from the registry.

**Solution**:
- Pre-pull the image: `make docker-init`
- Check Pod events: `kubectl describe pod sandbox-XXX -n deer-flow`
- Check node: `kubectl get nodes`

### Issue: Cannot access sandbox URL from backend

**Cause**: The backend cannot resolve or reach the sandbox ClusterIP Service DNS. This usually means the backend is not running inside the same Kubernetes cluster/network or cluster DNS/network policy is blocking access.

**Solution**:
- Verify the Service exists: `kubectl get svc -n deer-flow`
- In NodePort mode, test from the backend container: `curl http://$NODE_HOST:NODE_PORT/v1/sandbox`
- In ClusterIP mode, test from the backend Pod: `curl http://sandbox-XXX-svc.deer-flow.svc.cluster.local:8080/v1/sandbox`
- Check `NODE_HOST` for NodePort deployments, or cluster DNS / NetworkPolicy / service mesh rules for ClusterIP deployments

## Running several replicas

The provisioner keeps no state of its own between requests, so several
replicas can serve the same backend behind one load-balanced Service (the Helm
chart's `provisioner.replicas`; compose runs a single container):

- The sandbox Pods and Services it creates carry the labels it later queries
  (`app=deer-flow-sandbox`, `sandbox-id`). They are the only registry: create,
  status, list and delete all read the Kubernetes API, never a process-local
  table, so any replica can answer for a sandbox another replica created.
- `POST /api/sandboxes` is idempotent across replicas. Two creates for the same
  `sandbox_id` that race on different replicas both succeed: the loser's Pod
  and Service creates return `409 AlreadyExists`, which the handler treats like
  its own success before reading the winner's objects back (including
  `MAX_SHELL_SESSIONS`, so a lower-capacity winner is still reported to the
  Gateway as `409`). Several Gateway Pods already run this race against a
  single provisioner.
- `DELETE /api/sandboxes/{sandbox_id}` tolerates `404`, so two replicas
  deleting the same sandbox both return success.
- NodePorts are allocated by the API server when the Service is created; the
  provisioner only reads the assigned port back.
- No replica runs a background loop (there is no reaper or cache), and
  `/api/capabilities` is derived from environment variables every replica of
  one Deployment shares.

The one startup write is `_ensure_namespace()`: when `K8S_NAMESPACE` does not
exist yet, two replicas starting together can both see `404` and race to create
it; the loser's `409` is not caught, so that process exits and is restarted into
the now-existing namespace. Under the Helm chart the provisioner runs inside the
namespace it manages, so this path never runs there.

## Security Considerations

1. **HostPath Volumes**: The provisioner mounts host directories into sandbox Pods by default. Ensure these paths contain only trusted data. For production, prefer PVC-backed user-data shared with the Gateway to avoid node-specific data loss risks. Configure skills according to [PVC skills setup](#pvc-skills-setup): explicit lead Agent policies use the shared user-data PVC, while unrestricted threads need an operator-populated skills PVC.

2. **Resource Limits**: Each sandbox Pod has CPU, memory, and storage limits to prevent resource exhaustion.

3. **Network Isolation**: Sandbox Pods run in the configured namespace and are exposed through NodePort or ClusterIP Services. Prefer ClusterIP with NetworkPolicies for in-cluster deployments.

4. **kubeconfig Access**: The provisioner has full access to your Kubernetes cluster via the mounted kubeconfig. Run it only in trusted environments.

5. **Image Trust**: The sandbox image should come from a trusted registry. Review and audit the image contents.

## Future Enhancements

- [ ] Support for custom resource requests/limits per sandbox
- [x] PersistentVolume support for larger data requirements
- [ ] Automatic cleanup of stale sandboxes (timeout-based)
- [ ] Metrics and monitoring (Prometheus integration)
- [ ] Multi-cluster support (route to different K8s clusters)
- [ ] Pod affinity/anti-affinity rules for better placement
- [ ] NetworkPolicy templates for sandbox isolation
