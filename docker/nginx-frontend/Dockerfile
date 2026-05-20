# nginx + Node.js combined image for serving pre-built Next.js dist
#
# Usage:
#   Build frontend dist: make docker-build-frontend-dist
#   Extract dist:        docker compose run --rm frontend-dist
#   Start services:      make docker-start-backend-dev

FROM nginx:latest

# Install Node.js 22 + pnpm
RUN apt-get update && apt-get install -y curl ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g corepack && corepack enable && \
    corepack install -g pnpm@10.26.2 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY start.sh /start.sh
RUN chmod +x /start.sh

CMD ["/start.sh"]
