ARG BASE_IMAGE=enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest
FROM ${BASE_IMAGE}

ARG PIP_INDEX_URL

COPY features-tool /opt/features-tool
COPY features-tool/requirements.txt /tmp/features-tool-requirements.txt

RUN python3 -m pip install --no-cache-dir \
    ${PIP_INDEX_URL:+--index-url "$PIP_INDEX_URL"} \
    -r /tmp/features-tool-requirements.txt \
 && rm -f /tmp/features-tool-requirements.txt
