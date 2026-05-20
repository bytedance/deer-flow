FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python:3.12-slim-bookworm

ARG APT_MIRROR
ARG PIP_INDEX_URL

# Alibaba Cloud Debian mirror for restricted networks
RUN sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    sed -i 's|https://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || true

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*
# Install Python dependencies
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir \
    ${PIP_INDEX_URL:+--index-url "$PIP_INDEX_URL"} \
    fastapi \
    "uvicorn[standard]" \
    kubernetes

WORKDIR /app
COPY app.py .

EXPOSE 8002

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8002"]
