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
                          │ (via Docker │ NodePort│  Pod(s)  │
                          │   network)  │         └──────────┘
                          └─────────────┘
```

### How It Works

1. **Backend Request**: When the backend needs to execute code, it sends a `POST /api/sandboxes` request with a `sandbox_id` and `thread_id`.

2. **Pod Creation**: The provisioner creates a dedicated Pod in the `deer-flow` namespace with:
   - The sandbox container image (all-in-one-sandbox)
   - HostPath volumes mounted for:
     - `/mnt/skills` → Read-only access to public skills
     - `/mnt/user-data` → Read-write access to thread-specific data
   - Resource limits (CPU, memory, ephemeral storage)
   - Readiness/liveness probes

3. **Service Creation**: A NodePort Service is created to expose the Pod, with Kubernetes auto-allocating a port from the NodePort range (typically 30000-32767).

4. **Access URL**: The provisioner returns `http://host.docker.internal:{NodePort}` to the backend, which the backend containers can reach directly.

5. **Cleanup**: When the session ends, `DELETE /api/sandboxes/{sandbox_id}` removes both the Pod and Service.

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
  "thread_id": "thread-456"
}
```

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
| `SANDBOX_IMAGE` | `enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest` | Container image for sandbox Pods |
| `SKILLS_HOST_PATH` | - | **Host machine** path to skills directory (must be absolute) |
| `THREADS_HOST_PATH` | - | **Host machine** path to threads data directory (must be absolute) |
| `KUBECONFIG_PATH` | `/root/.kube/config` | Path to kubeconfig **inside** the provisioner container |
| `NODE_HOST` | `host.docker.internal` | Hostname that backend containers use to reach host NodePorts |
| `K8S_API_SERVER` | (from kubeconfig) | Override K8s API server URL (e.g., `https://host.docker.internal:26443`) |

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
   - The `SKILLS_HOST_PATH` and `THREADS_HOST_PATH` must be **absolute paths on the host machine**
   - These paths are mounted into sandbox Pods via K8s HostPath volumes
   - The paths must exist and be readable by the K8s node

### Docker Compose Setup

The provisioner runs as part of the docker-compose-dev stack:

```bash
# Start all services including provisioner
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
  -d '{"sandbox_id":"test-001","thread_id":"thread-001"}'

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
- Use absolute paths for `SKILLS_HOST_PATH` and `THREADS_HOST_PATH`
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

**Cause**: NodePort not reachable or `NODE_HOST` misconfigured.

**Solution**:
- Verify the Service exists: `kubectl get svc -n deer-flow`
- Test from host: `curl http://localhost:NODE_PORT/v1/sandbox`
- Ensure `extra_hosts` is set in docker-compose (Linux)
- Check `NODE_HOST` env var matches how backend reaches host

## Security Considerations

1. **HostPath Volumes**: The provisioner mounts host directories into sandbox Pods. Ensure these paths contain only trusted data.

2. **Resource Limits**: Each sandbox Pod has CPU, memory, and storage limits to prevent resource exhaustion.

3. **Network Isolation**: Sandbox Pods run in the `deer-flow` namespace but share the host's network namespace via NodePort. Consider NetworkPolicies for stricter isolation.

4. **kubeconfig Access**: The provisioner has full access to your Kubernetes cluster via the mounted kubeconfig. Run it only in trusted environments.

5. **Image Trust**: The sandbox image should come from a trusted registry. Review and audit the image contents.

## Future Enhancements

- [ ] Support for custom resource requests/limits per sandbox
- [ ] PersistentVolume support for larger data requirements
- [ ] Automatic cleanup of stale sandboxes (timeout-based)
- [ ] Metrics and monitoring (Prometheus integration)
- [ ] Multi-cluster support (route to different K8s clusters)
- [ ] Pod affinity/anti-affinity rules for better placement
- [ ] NetworkPolicy templates for sandbox isolation
