FROM node:22-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# standalone 本身已经是根结构
COPY frontend/.next/standalone ./

# 静态资源要对应路径
COPY frontend/.next/static ./.next/static

# public 也放根
COPY frontend/public ./public

EXPOSE 3000

CMD ["node", "server.js"]