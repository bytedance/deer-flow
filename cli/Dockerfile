FROM python:3.12-slim-bookworm

COPY backend/packages/harness /harness
RUN pip install --no-cache-dir /harness

CMD ["tail", "-f", "/dev/null"]
