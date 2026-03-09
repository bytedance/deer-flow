ARG BASE_IMAGE=enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest
FROM ${BASE_IMAGE}

USER root

ENV DEBIAN_FRONTEND=noninteractive
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PIP_NO_CACHE_DIR=1

RUN apt-get -o Acquire::Retries=5 update && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
    libgtk-4-1 \
    libgraphene-1.0-0 \
    libevent-2.1-7 \
    libavif13 \
    libmanette-0.2-0 \
    libenchant-2-2 \
    libhyphen0 \
    libsecret-1-0 \
    gstreamer1.0-gl \
    libgstreamer-gl1.0-0 \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    libgstreamer-plugins-base1.0-0 \
    libwoff1 \
    woff2 \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install \
    crawl4ai \
    playwright \
    pypdf \
    requests \
    beautifulsoup4 \
    rich \
    python-dotenv

RUN python -m playwright install chromium && \
    mkdir -p /ms-playwright
