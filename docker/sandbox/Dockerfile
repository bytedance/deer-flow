ARG BASE_IMAGE=enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest
FROM ${BASE_IMAGE}

# 安装 weasyprint PDF 渲染所需的 GTK/Cairo/Pango 系统运行时库
# 以及文泉驿正黑字体用于 CJK 文字渲染
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libpangoft2-1.0-0 \
    fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/*

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# 安装沙箱容器依赖
COPY docker/sandbox/requirements.txt /tmp/sandbox-requirements.txt

RUN python3 -m pip install --no-cache-dir \
    ${PIP_INDEX_URL:+--index-url "$PIP_INDEX_URL"} \
    -r /tmp/sandbox-requirements.txt \
 && rm -f /tmp/sandbox-requirements.txt

# features-tool 代码直接从 /mnt/skills/custom/features-tool 加载（沙箱启动时挂载）
