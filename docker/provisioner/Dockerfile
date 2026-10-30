FROM python:3.12-slim-bookworm

ARG APT_MIRROR
ARG PIP_INDEX_URL

# Optionally override apt mirror for restricted networks (e.g. APT_MIRROR=mirrors.aliyun.com)
RUN if [ -n "${APT_MIRROR}" ]; then \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list 2>/dev/null || true; \
    fi

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir \
    ${PIP_INDEX_URL:+--index-url "$PIP_INDEX_URL"} \
    fastapi \
    "uvicorn[standard]" \
    kubernetes

WORKDIR /app
COPY app.py .

# Run as an unprivileged user. The kubeconfig mount target must live under this
# user's home: /root is 0700 root:root in the base image, so a non-root process
# cannot traverse into /root/.kube/config (os.path.exists() returns False on
# EACCES and the client silently falls back to in-cluster config). Keep this
# path in sync with KUBECONFIG_PATH (see app.py and the compose mounts).
RUN useradd --create-home --uid 1000 deerflow \
    && install -d -o deerflow -g deerflow -m 0700 /home/deerflow/.kube
USER deerflow
ENV HOME=/home/deerflow

EXPOSE 8002

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8002"]
