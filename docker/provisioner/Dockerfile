# Base registry: defaults to mirror.gcr.io (Google's pull-through cache of Docker Hub
# library/* -- no rate limit, no auth). Avoids docker.io anon 100/6h/IP cap that wedged
# stax CI builds on 2026-05-09. Override w/ --build-arg BASE_REGISTRY=docker.io for
# upstream/local dev, or harbor.spooty.io/dockerhub once that proxy has upstream creds.
ARG BASE_REGISTRY=mirror.gcr.io
FROM ${BASE_REGISTRY}/library/python:3.12-slim-bookworm

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

EXPOSE 8002

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8002"]
