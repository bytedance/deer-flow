FROM python:3.12-slim-bookworm

COPY backend/packages/harness /harness
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple /harness

CMD ["tail", "-f", "/dev/null"]
