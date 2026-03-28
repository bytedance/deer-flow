FROM python:3.12-slim-bookworm AS builder
WORKDIR /app
COPY backend/requirements.txt /app/backend/
RUN pip install uv && cd /app/backend && uv sync --no-dev
COPY frontend/package.json /app/frontend/ && \
  corepack enable && corepack enable pnpm && \
  cd /app/frontend && pnpm install && pnpm build
COPY . /app/
FROM python:3.12-slim-bookworm AS runner
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y curl nginx ca-certificates gnupg && \
  curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
  echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" > /etc/apt/sources.list.d/nodesource.list && \
  apt-get update && apt-get install -y nodejs && apt-get autoremove && rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv
COPY --from=builder /app /app
WORKDIR /app
COPY start.sh deploy.sh /app/
RUN chmod +x /app/start.sh /app/deploy.sh
ENV CI=true DEER_FLOW_HOME=/persist/.deer-flow PYTHONPATH=/app/backend:$PYTHONPATH NODE_ENV=production PORT=8080
VOLUME ["/persist"]
EXPOSE 8080
ENTRYPOINT ["/app/start.sh"]
