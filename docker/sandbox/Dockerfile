ARG BASE_IMAGE=enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest
FROM ${BASE_IMAGE}

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# 安装沙箱容器依赖
COPY docker/sandbox/requirements.txt /tmp/sandbox-requirements.txt

RUN python3 -m pip install --no-cache-dir \
    ${PIP_INDEX_URL:+--index-url "$PIP_INDEX_URL"} \
    -r /tmp/sandbox-requirements.txt \
 && rm -f /tmp/sandbox-requirements.txt

# features-tool 代码直接从 /mnt/skills/custom/features-tool 加载（沙箱启动时挂载）
