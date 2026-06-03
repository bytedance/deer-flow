ARG BASE_IMAGE=enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest
FROM ${BASE_IMAGE}

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# ── Install Python 3.12 (required by deerflow-harness >=3.12) ──
# The base image ships Python 3.10; deerflow-harness needs 3.12.
# deadsnakes PPA provides pre-built Python 3.12 for Ubuntu.
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
 && add-apt-repository -y ppa:deadsnakes/ppa \
 && apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
 && rm -rf /var/lib/apt/lists/*

# Ensure pip is available for Python 3.12
RUN python3.12 -m ensurepip --upgrade \
 || (apt-get update && apt-get install -y --no-install-recommends wget \
     && wget -q https://bootstrap.pypa.io/get-pip.py -O /tmp/get-pip.py \
     && python3.12 /tmp/get-pip.py \
     && rm /tmp/get-pip.py \
     && rm -rf /var/lib/apt/lists/*)

# ── Install CLI bridge dependencies for Python 3.12 (minimal, no langchain/langgraph) ──
COPY docker/sandbox/requirements-deerflow-cli.txt /tmp/requirements-deerflow-cli.txt
RUN python3.12 -m pip install --no-cache-dir \
    ${PIP_INDEX_URL:+--index-url "$PIP_INDEX_URL"} \
    -r /tmp/requirements-deerflow-cli.txt \
 && rm -f /tmp/requirements-deerflow-cli.txt

# ── Install latest deerflow-harness for Python 3.12 (contains integrations/cli.py with --params-file) ──
COPY backend/packages/harness /tmp/deerflow-harness
RUN python3.12 -m pip install --no-cache-dir --no-deps \
    ${PIP_INDEX_URL:+--index-url "$PIP_INDEX_URL"} \
    /tmp/deerflow-harness \
 && rm -rf /tmp/deerflow-harness

# ── Features-tool (installed on system python3.10, not python3.12) ──
COPY docker/sandbox/features-tool/requirements.txt /tmp/features-tool-requirements.txt
RUN mkdir -p /opt/features-tool/models

RUN python3 -m pip install --no-cache-dir \
    ${PIP_INDEX_URL:+--index-url "$PIP_INDEX_URL"} \
    -r /tmp/features-tool-requirements.txt \
 && rm -f /tmp/features-tool-requirements.txt

COPY docker/sandbox/features-tool /opt/features-tool
