ARG BASE_IMAGE=python:3.12-alpine
FROM ${BASE_IMAGE}

# BASE_IMAGE is overridable for offline smoke tests. Production uses the small
# official Python Alpine image; a cached Alpine-derived base can install Python.
RUN if ! command -v python >/dev/null 2>&1; then apk add --no-cache python3 && ln -sf /usr/bin/python3 /usr/bin/python; fi

COPY backend/packages/harness/deerflow/community/aio_sandbox/network_proxy.py /opt/deerflow-network-proxy.py

USER 65532:65532
CMD ["python", "/opt/deerflow-network-proxy.py", "serve"]
