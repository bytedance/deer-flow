# Kubernetes Deployment Guide for DeerFlow

This guide provides instructions for deploying DeerFlow on Kubernetes, including production-ready manifests and configuration examples.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Architecture Overview](#architecture-overview)
- [Preparing Configuration](#preparing-configuration)
- [Deploying to Kubernetes](#deploying-to-kubernetes)
- [Service Configuration](#service-configuration)
- [Ingress Setup](#ingress-setup)
- [Scaling and High Availability](#scaling-and-high-availability)
- [Monitoring and Health Checks](#monitoring-and-health-checks)
- [Troubleshooting](#troubleshooting)

## Prerequisites

Before deploying DeerFlow on Kubernetes, ensure you have:

- A running Kubernetes cluster (v1.25+)
- `kubectl` configured to access your cluster
- Docker images built and available in a container registry
- Sufficient cluster resources (see [Resource Requirements](#resource-requirements))

### Required Tools

```bash
# Verify kubectl access
kubectl version --client

# Verify cluster access
kubectl cluster-info

# Check available namespaces
kubectl get namespaces
```

## Architecture Overview

DeerFlow consists of four main services when deployed on Kubernetes:

```
┌─────────────────────────────────────────────────────────────────┐
│                         Ingress Controller                        │
│                      (nginx-ingress / Traefik)                   │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                           nginx                                   │
│                    (Reverse Proxy - :2026)                        │
└─────────────────────────────────────────────────────────────────┘
                    │                         │
                    ▼                         ▼
┌───────────────────────────┐   ┌─────────────────────────────────┐
│         frontend           │   │            gateway                │
│   (Next.js - Port 3000)    │   │   (FastAPI - Port 8001)          │
│                           │   │   - Gateway API                   │
│                           │   │   - Agent Runtime                 │
│                           │   │   - LangGraph Server              │
└───────────────────────────┘   └─────────────────────────────────┘
```

## Preparing Configuration

### 1. Create Namespace

Create a dedicated namespace for DeerFlow:

```yaml
# namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: deer-flow
  labels:
    app.kubernetes.io/name: deer-flow
    app.kubernetes.io/managed-by: kubectl
```

```bash
kubectl apply -f namespace.yaml
```

### 2. Create ConfigMap

Create a ConfigMap for non-sensitive configuration:

```yaml
# configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: deer-flow-config
  namespace: deer-flow
data:
  DEER_FLOW_CONFIG_PATH: "/app/backend/config.yaml"
  DEER_FLOW_EXTENSIONS_CONFIG_PATH: "/app/backend/extensions_config.json"
  DEER_FLOW_HOME: "/app/backend/.deer-flow"
  DEER_FLOW_CHANNELS_LANGGRAPH_URL: "http://gateway:8001/api"
  DEER_FLOW_CHANNELS_GATEWAY_URL: "http://gateway:8001"
  DEER_FLOW_SANDBOX_HOST: "gateway"
  DEER_FLOW_HOST_BASE_DIR: "/app/backend/.deer-flow"
---
# Note: Copy your config.yaml and extensions_config.json to the cluster
# These should be mounted as volumes or stored in a Secret
```

### 3. Create Secrets

Create a Secret for sensitive configuration and API keys:

```yaml
# secrets.yaml
apiVersion: v1
kind: Secret
metadata:
  name: deer-flow-secrets
  namespace: deer-flow
type: Opaque
stringData:
  # API Keys - replace with your actual values
  OPENAI_API_KEY: "sk-your-openai-key"
  ANTHROPIC_API_KEY: "sk-ant-your-anthropic-key"

  # Optional: Better Auth Secret for session security
  BETTER_AUTH_SECRET: "your-random-secret-here-min-32-chars"

  # Configuration files (base64 encoded)
  config.yaml: |
    # Your config.yaml content here
  extensions_config.json: |
    # Your extensions config here
```

```bash
kubectl apply -f secrets.yaml
```

## Deploying to Kubernetes

### Gateway Service

The Gateway is the core FastAPI service handling API requests and agent runtime.

```yaml
# gateway-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: deer-flow-gateway
  namespace: deer-flow
  labels:
    app: deer-flow
    component: gateway
spec:
  replicas: 2
  selector:
    matchLabels:
      app: deer-flow
      component: gateway
  template:
    metadata:
      labels:
        app: deer-flow
        component: gateway
    spec:
      containers:
        - name: gateway
          image: deer-flow-gateway:latest
          imagePullPolicy: IfNotPresent
          ports:
            - name: http
              containerPort: 8001
              protocol: TCP
          env:
            - name: CI
              value: "true"
            - name: DEER_FLOW_HOME
              valueFrom:
                configMapKeyRef:
                  name: deer-flow-config
                  key: DEER_FLOW_HOME
            - name: DEER_FLOW_CONFIG_PATH
              valueFrom:
                configMapKeyRef:
                  name: deer-flow-config
                  key: DEER_FLOW_CONFIG_PATH
            - name: DEER_FLOW_EXTENSIONS_CONFIG_PATH
              valueFrom:
                configMapKeyRef:
                  name: deer-flow-config
                  key: DEER_FLOW_EXTENSIONS_CONFIG_PATH
            - name: DEER_FLOW_CHANNELS_LANGGRAPH_URL
              valueFrom:
                configMapKeyRef:
                  name: deer-flow-config
                  key: DEER_FLOW_CHANNELS_LANGGRAPH_URL
            - name: OPENAI_API_KEY
              valueFrom:
                secretKeyRef:
                  name: deer-flow-secrets
                  key: OPENAI_API_KEY
            - name: ANTHROPIC_API_KEY
              valueFrom:
                secretKeyRef:
                  name: deer-flow-secrets
                  key: ANTHROPIC_API_KEY
          resources:
            requests:
              cpu: 500m
              memory: 1Gi
            limits:
              cpu: 2000m
              memory: 4Gi
          livenessProbe:
            httpGet:
              path: /health
              port: 8001
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 5
          readinessProbe:
            httpGet:
              path: /health
              port: 8001
            initialDelaySeconds: 10
            periodSeconds: 5
          volumeMounts:
            - name: config
              mountPath: /app/backend/config.yaml
              subPath: config.yaml
              readOnly: true
            - name: extensions-config
              mountPath: /app/backend/extensions_config.json
              subPath: extensions_config.json
              readOnly: true
            - name: deer-flow-data
              mountPath: /app/backend/.deer-flow
      volumes:
        - name: config
          secret:
            secretName: deer-flow-secrets
            items:
              - key: config.yaml
                path: config.yaml
        - name: extensions-config
          secret:
            secretName: deer-flow-secrets
            items:
              - key: extensions_config.json
                path: extensions_config.json
        - name: deer-flow-data
          persistentVolumeClaim:
            claimName: deer-flow-data-pvc

---
apiVersion: v1
kind: Service
metadata:
  name: deer-flow-gateway
  namespace: deer-flow
spec:
  type: ClusterIP
  ports:
    - name: http
      port: 8001
      targetPort: 8001
      protocol: TCP
  selector:
    app: deer-flow
    component: gateway
```

### Frontend Service

The Next.js frontend serving the web interface.

```yaml
# frontend-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: deer-flow-frontend
  namespace: deer-flow
  labels:
    app: deer-flow
    component: frontend
spec:
  replicas: 2
  selector:
    matchLabels:
      app: deer-flow
      component: frontend
  template:
    metadata:
      labels:
        app: deer-flow
        component: frontend
    spec:
      containers:
        - name: frontend
          image: deer-flow-frontend:latest
          imagePullPolicy: IfNotPresent
          ports:
            - name: http
              containerPort: 3000
              protocol: TCP
          env:
            - name: BETTER_AUTH_SECRET
              valueFrom:
                secretKeyRef:
                  name: deer-flow-secrets
                  key: BETTER_AUTH_SECRET
            - name: DEER_FLOW_INTERNAL_GATEWAY_BASE_URL
              value: "http://deer-flow-gateway:8001"
          resources:
            requests:
              cpu: 100m
              memory: 256Mi
            limits:
              cpu: 500m
              memory: 1Gi
          livenessProbe:
            httpGet:
              path: /
              port: 3000
            initialDelaySeconds: 15
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /
              port: 3000
            initialDelaySeconds: 5
            periodSeconds: 5

---
apiVersion: v1
kind: Service
metadata:
  name: deer-flow-frontend
  namespace: deer-flow
spec:
  type: ClusterIP
  ports:
    - name: http
      port: 3000
      targetPort: 3000
      protocol: TCP
  selector:
    app: deer-flow
    component: frontend
```

### Nginx Reverse Proxy

The nginx reverse proxy routing traffic to frontend and gateway.

```yaml
# nginx-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: deer-flow-nginx
  namespace: deer-flow
  labels:
    app: deer-flow
    component: nginx
spec:
  replicas: 2
  selector:
    matchLabels:
      app: deer-flow
      component: nginx
  template:
    metadata:
      labels:
        app: deer-flow
        component: nginx
    spec:
      containers:
        - name: nginx
          image: nginx:alpine
          ports:
            - name: http
              containerPort: 2026
              protocol: TCP
          volumeMounts:
            - name: nginx-config
              mountPath: /etc/nginx/nginx.conf
              subPath: nginx.conf
              readOnly: true
          resources:
            requests:
              cpu: 50m
              memory: 64Mi
            limits:
              cpu: 200m
              memory: 256Mi
          livenessProbe:
            tcpSocket:
              port: 2026
            initialDelaySeconds: 10
            periodSeconds: 10
          readinessProbe:
            tcpSocket:
              port: 2026
            initialDelaySeconds: 5
            periodSeconds: 5
      volumes:
        - name: nginx-config
          configMap:
            name: deer-flow-nginx-config

---
apiVersion: v1
kind: Service
metadata:
  name: deer-flow-nginx
  namespace: deer-flow
spec:
  type: ClusterIP
  ports:
    - name: http
      port: 2026
      targetPort: 2026
      protocol: TCP
  selector:
    app: deer-flow
    component: nginx
```

### Nginx Configuration ConfigMap

```yaml
# nginx-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: deer-flow-nginx-config
  namespace: deer-flow
data:
  nginx.conf: |
    worker_processes auto;
    error_log /var/log/nginx/error.log warn;
    pid /var/run/nginx.pid;

    events {
        worker_connections 1024;
    }

    http {
        include /etc/nginx/mime.types;
        default_type application/octet-stream;

        log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                        '$status $body_bytes_sent "$http_referer" '
                        '"$http_user_agent" "$http_x_forwarded_for"';

        access_log /var/log/nginx/access.log main;

        sendfile on;
        tcp_nopush on;
        tcp_nodelay on;
        keepalive_timeout 65;
        types_hash_max_size 2048;

        # Frontend
        upstream frontend {
            server deer-flow-frontend:3000;
        }

        # Gateway API
        upstream gateway {
            server deer-flow-gateway:8001;
        }

        server {
            listen 2026;
            server_name _;

            # Health check endpoint
            location /health {
                return 200 'OK';
                add_header Content-Type text/plain;
            }

            # Gateway API routes
            location /api/ {
                proxy_pass http://gateway;
                proxy_http_version 1.1;
                proxy_set_header Upgrade $http_upgrade;
                proxy_set_header Connection 'upgrade';
                proxy_set_header Host $host;
                proxy_set_header X-Real-IP $remote_addr;
                proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                proxy_set_header X-Forwarded-Proto $scheme;
                proxy_cache_bypass $http_upgrade;

                # SSE/streaming support
                proxy_buffering off;
                proxy_read_timeout 86400;
            }

            # Frontend (catch-all)
            location / {
                proxy_pass http://frontend;
                proxy_http_version 1.1;
                proxy_set_header Upgrade $http_upgrade;
                proxy_set_header Connection 'upgrade';
                proxy_set_header Host $host;
                proxy_set_header X-Real-IP $remote_addr;
                proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                proxy_set_header X-Forwarded-Proto $scheme;
                proxy_cache_bypass $http_upgrade;
            }
        }
    }
```

### Persistent Volume Claim

For storing runtime data:

```yaml
# pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: deer-flow-data-pvc
  namespace: deer-flow
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  storageClassName: standard
```

## Ingress Setup

Expose DeerFlow externally using an Ingress controller:

```yaml
# ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: deer-flow-ingress
  namespace: deer-flow
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
    nginx.ingress.kubernetes.io/proxy-body-size: "100m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "86400"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "86400"
spec:
  ingressClassName: nginx
  rules:
    - host: deer-flow.example.com
      http:
        paths:
          - path: /api
            pathType: Prefix
            backend:
              service:
                name: deer-flow-nginx
                port:
                  number: 2026
          - path: /
            pathType: Prefix
            backend:
              service:
                name: deer-flow-nginx
                port:
                  number: 2026
  tls:
    - hosts:
        - deer-flow.example.com
      secretName: deer-flow-tls-secret
```

## Scaling and High Availability

### Horizontal Pod Autoscaler

Enable autoscaling for the gateway service:

```yaml
# hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: deer-flow-gateway-hpa
  namespace: deer-flow
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: deer-flow-gateway
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
```

### Resource Requirements

Recommended resource allocation per service:

| Service | CPU Request | CPU Limit | Memory Request | Memory Limit |
|---------|-------------|-----------|----------------|--------------|
| Gateway | 500m | 2000m | 1Gi | 4Gi |
| Frontend | 100m | 500m | 256Mi | 1Gi |
| Nginx | 50m | 200m | 64Mi | 256Mi |

### Cluster Requirements

Minimum cluster configuration for production:

| Component | Specification |
|-----------|---------------|
| Master Nodes | 3x (2 vCPU, 4GB RAM) |
| Worker Nodes | 3x (4 vCPU, 8GB RAM) |
| Total CPU | 12+ cores |
| Total Memory | 24+ GB |
| Storage | 50+ GB |

## Monitoring and Health Checks

### Pod Disruption Budget

Ensure high availability during node maintenance:

```yaml
# pdb.yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: deer-flow-pdb
  namespace: deer-flow
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: deer-flow
```

### Resource Quotas

Set namespace resource quotas:

```yaml
# resource-quota.yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: deer-flow-quota
  namespace: deer-flow
spec:
  hard:
    requests.cpu: "4"
    requests.memory: 8Gi
    limits.cpu: "8"
    limits.memory: 16Gi
    pods: "20"
```

## Troubleshooting

### Common Issues

#### 1. Pods Not Starting

```bash
# Check pod status
kubectl get pods -n deer-flow

# View pod events
kubectl describe pod <pod-name> -n deer-flow

# Check pod logs
kubectl logs <pod-name> -n deer-flow
```

#### 2. Service Connectivity Issues

```bash
# Verify services are running
kubectl get svc -n deer-flow

# Test internal connectivity
kubectl run test --rm -it --image=busybox -- /bin/sh
# Then from the shell:
# wget -qO- http://deer-flow-gateway:8001/health
```

#### 3. Configuration Problems

```bash
# Verify ConfigMap
kubectl get configmap deer-flow-config -n deer-flow -o yaml

# Verify Secrets
kubectl get secret deer-flow-secrets -n deer-flow -o yaml
```

### Deployment Commands

```bash
# Apply all manifests
kubectl apply -f namespace.yaml
kubectl apply -f secrets.yaml
kubectl apply -f configmap.yaml
kubectl apply -f pvc.yaml
kubectl apply -f gateway-deployment.yaml
kubectl apply -f frontend-deployment.yaml
kubectl apply -f nginx-deployment.yaml
kubectl apply -f nginx-configmap.yaml
kubectl apply -f ingress.yaml

# Verify deployment
kubectl get all -n deer-flow

# Watch pod status
kubectl get pods -n deer-flow -w

# Check ingress
kubectl describe ingress deer-flow-ingress -n deer-flow
```

### Cleanup

```bash
# Delete all resources
kubectl delete -f ingress.yaml
kubectl delete -f nginx-configmap.yaml
kubectl delete -f nginx-deployment.yaml
kubectl delete -f frontend-deployment.yaml
kubectl delete -f gateway-deployment.yaml
kubectl delete -f pvc.yaml
kubectl delete -f configmap.yaml
kubectl delete -f secrets.yaml
kubectl delete -f namespace.yaml
```

## Production Checklist

Before going to production, ensure:

- [ ] All Secrets are properly configured with real values
- [ ] Ingress/TLS is properly configured
- [ ] Resource limits are set appropriately
- [ ] Health checks are configured
- [ ] Logging is configured (ELK, Loki, etc.)
- [ ] Monitoring is set up (Prometheus, Grafana)
- [ ] Backup strategy is in place
- [ ] Disaster recovery plan is documented
- [ ] Security scanning is enabled
- [ ] Network policies are configured
